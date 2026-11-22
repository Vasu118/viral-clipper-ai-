import os, uuid, shutil, subprocess, json, re, threading, time
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BASE=Path(os.getenv("DATA_DIR","/data"))
UPLOADS=BASE/"uploads"; OUT=BASE/"outputs"
UPLOADS.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
JOBS: Dict[str,Dict[str,Any]]={}
app=FastAPI(title="Viral Clipper AI API")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","*").split(","),allow_methods=["*"],allow_headers=["*"])

def run(cmd):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if p.returncode: raise RuntimeError(p.stderr[-2500:])
    return p.stdout.strip()

def srt_time(sec):
    ms=int(sec*1000); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def get_duration(path):
    return float(run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)]))

def transcribe(path):
    from faster_whisper import WhisperModel
    model=WhisperModel(os.getenv("WHISPER_MODEL","small"),device=os.getenv("WHISPER_DEVICE","cpu"),compute_type=os.getenv("WHISPER_COMPUTE_TYPE","int8"))
    segments,info=model.transcribe(str(path),vad_filter=True,word_timestamps=False)
    return [{"start":float(s.start),"end":float(s.end),"text":s.text.strip()} for s in segments if s.text.strip()], info.language

def score(seg):
    t=seg["text"].lower()
    # Heuristic highlight score; not a guarantee of virality.
    hooks=["but","because","why","how","secret","mistake","never","best","worst","amazing","shocking","સાચું","શા માટે","કેવી રીતે","ભૂલ","રહસ્ય","लेकिन","क्यों","कैसे","गलती","कमाल","सच"]
    return min(len(t)/100,1.5)+sum(0.45 for w in hooks if w in t)+ (0.4 if "?" in t else 0)

def choose_clips(segments,count,maxdur):
    if not segments: return []
    total=max(1,segments[-1]["end"]-segments[0]["start"])
    candidates=[]
    for i,s in enumerate(segments):
        start=max(0,s["start"]-2); end=min(segments[-1]["end"],start+maxdur)
        if end-start<8: continue
        group=[x for x in segments if x["start"]<end and x["end"]>start]
        txt=" ".join(x["text"] for x in group)
        sc=sum(score(x) for x in group)/max(1,len(group))
        # Prefer self-contained transcript sections with adequate speech.
        sc += min(len(txt)/300,1)
        candidates.append((sc,start,end,group))
    candidates.sort(reverse=True,key=lambda x:x[0])
    chosen=[]
    for c in candidates:
        if all(c[2] < x[1] or c[1] > x[2] for x in chosen):
            chosen.append(c)
        if len(chosen)>=count: break
    if not chosen:
        chosen=[(0,segments[0]["start"],min(segments[-1]["end"],segments[0]["start"]+maxdur),segments)]
    return sorted(chosen,key=lambda x:x[1])

def write_srt(groups, path, lang):
    lines=[]; n=1
    for seg in groups:
        txt=seg["text"]
        # Preserve spoken language as recognized. Translation can be added via a configured provider.
        lines += [str(n),f"{srt_time(seg['start'])} --> {srt_time(seg['end'])}",txt,""]; n+=1
    path.write_text("\n".join(lines),encoding="utf-8")

def process(job_id, video, count, maxdur, language):
    job=JOBS[job_id]
    try:
        job.update(status="processing",progress=12,message="Audio transcription running…")
        segments,detected=transcribe(video)
        job.update(progress=42,message=f"Transcript ready ({detected}). Finding highlights…")
        selections=choose_clips(segments,count,maxdur)
        if not selections: raise RuntimeError("No speech segments found in this video.")
        clips=[]
        for i,(_,start,end,group) in enumerate(selections,1):
            job.update(progress=45+int(45*i/len(selections)),message=f"Rendering clip {i}/{len(selections)}…")
            folder=OUT/job_id; folder.mkdir(exist_ok=True)
            srt=folder/f"clip_{i}.srt"; write_srt(group,srt,detected)
            mp4=folder/f"clip_{i}.mp4"
            # Center crop to vertical 9:16. Subtitles are burned in for universal phone playback.
            vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
            # Escape subtitle path for ffmpeg filter syntax.
            sp=str(srt.resolve()).replace("\\","/").replace(":","\\:")
            vf+=f",subtitles='{sp}':force_style='FontSize=18,Outline=2,Shadow=1,Alignment=2,MarginV=100'"
            run(["ffmpeg","-y","-ss",str(start),"-i",str(video),"-t",str(end-start),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k","-movflags","+faststart",str(mp4)])
            clips.append({"duration":round(end-start,1),"download_url":f"/files/{job_id}/clip_{i}.mp4"})
        job.update(status="completed",progress=100,message="તમારી ક્લિપ્સ તૈયાર છે.",clips=clips)
    except Exception as e:
        job.update(status="failed",progress=100,message=str(e)[:1000])
    finally:
        try: video.unlink(missing_ok=True)
        except: pass

@app.post("/api/jobs")
async def create_job(video: UploadFile=File(...),count:int=Form(5),max_duration:int=Form(45),language:str=Form("both")):
    if not video.filename: raise HTTPException(400,"Missing video file")
    if count not in (3,5,10) or max_duration not in (30,45,60): raise HTTPException(400,"Invalid clip settings")
    ext=Path(video.filename).suffix.lower()
    if ext not in (".mp4",".mov",".mkv",".webm",".m4v"): raise HTTPException(400,"Unsupported video type")
    jid=uuid.uuid4().hex
    path=UPLOADS/f"{jid}{ext}"
    with path.open("wb") as f: shutil.copyfileobj(video.file,f)
    if path.stat().st_size>2*1024**3:
        path.unlink(missing_ok=True); raise HTTPException(413,"Video must be smaller than 2 GB")
    JOBS[jid]={"status":"queued","progress":3,"message":"Upload received","clips":[]}
    threading.Thread(target=process,args=(jid,path,count,max_duration,language),daemon=True).start()
    return {"job_id":jid}

@app.get("/api/jobs/{jid}")
def get_job(jid:str):
    if jid not in JOBS: raise HTTPException(404,"Job not found")
    return JOBS[jid]

@app.get("/files/{jid}/{filename}")
def get_file(jid:str,filename:str):
    from fastapi.responses import FileResponse
    p=OUT/jid/filename
    if not p.exists() or p.parent.resolve().parent!=OUT.resolve(): raise HTTPException(404,"File not found")
    return FileResponse(p,media_type="video/mp4",filename=filename)

app.mount("/",StaticFiles(directory="../frontend",html=True),name="frontend")
