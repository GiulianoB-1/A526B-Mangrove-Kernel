#!/usr/bin/env python3
"""P461 device-tree provenance: compare final boot FDT, flashed DTBO and live FDT.

Reads only offline dumps. Never writes boot/DTBO partitions. A downloaded
boot.img cannot identify the separate flashed DTBO or bootloader fixups.
"""
import argparse,hashlib,json,struct,subprocess,tempfile
from pathlib import Path

FDT_MAGIC=0xd00dfeed
DT_TABLE_MAGIC=0xd7b7ab1e
def digest(data):return hashlib.sha256(data).hexdigest()
def u32(b,i,be=True):return struct.unpack_from(">I" if be else "<I",b,i)[0]
def fdt(data):
    if len(data)<40 or u32(data,0)!=FDT_MAGIC:raise ValueError("not an FDT")
    head=struct.unpack_from(">10I",data)
    _,size,ofs,ofs_strings,_,_,_,_,size_strings,size_struct=head
    if size>len(data) or ofs+size_struct>size or ofs_strings+size_strings>size:
        raise ValueError("invalid FDT sections")
    out={};stack=[];pos=ofs
    strings=data[ofs_strings:ofs_strings+size_strings]
    while pos<ofs+size_struct:
        tok=u32(data,pos);pos+=4
        if tok==1:
            stop=data.find(b"\0",pos,ofs+size_struct)
            if stop<0:raise ValueError("unterminated FDT node")
            name=data[pos:stop].decode("utf-8","replace");pos=(stop+4)&~3
            stack.append(name)
            path="/" if len(stack)==1 else "/"+"/".join(stack[1:])
            if path in out:raise ValueError("duplicate path "+path)
            out[path]={}
        elif tok==2:
            if not stack:raise ValueError("unbalanced FDT")
            stack.pop()
        elif tok==3:
            if pos+8>ofs+size_struct:raise ValueError("short FDT property")
            length,name_off=struct.unpack_from(">II",data,pos);pos+=8
            if name_off>=len(strings):raise ValueError("bad property name")
            end=strings.find(b"\0",name_off)
            if end<0:raise ValueError("unterminated property name")
            key=strings[name_off:end].decode("utf-8","replace")
            val=data[pos:pos+length]
            if len(val)!=length:raise ValueError("short FDT property data")
            pos+=(length+3)&~3
            path="/" if len(stack)==1 else "/"+"/".join(stack[1:])
            out[path][key]=val
        elif tok==4:continue
        elif tok==9:
            if stack:raise ValueError("unbalanced FDT end")
            return out
        else:raise ValueError("unknown FDT token "+str(tok))
    raise ValueError("missing FDT end")
def cells(b):
    return [hex(u32(b,i)) for i in range(0,len(b),4)] if b and len(b)%4==0 else None
def strings(b):return [x.decode("utf8","replace") for x in b.rstrip(b"\0").split(b"\0")] if b else []
def suspicious(tree):
    items=[]
    for path,props in tree.items():
        if "ramoops" not in path.lower() and not any("ramoops" in v for v in strings(props.get("compatible",b""))):
            continue
        items.append({"path":path,
                      "compatible":strings(props.get("compatible",b"")),
                      "reg":cells(props.get("reg",b"")),
                      "ecc-size":cells(props.get("ecc-size",b"")),
                      "status":strings(props.get("status",b"")),
                      "is_reserved_memory":path.startswith("/reserved-memory/")})
    return items
def dtbo_images(raw):
    if u32(raw,0,be=False)!=DT_TABLE_MAGIC:raise ValueError("not Android DTBO table")
    if len(raw)<32:raise ValueError("short dtbo table")
    _,total,header_size,entry_size,count,entry_off,page_size,version=struct.unpack_from("<8I",raw)
    if total>len(raw) or header_size<32 or entry_size<32 or count>4096 or entry_off+count*entry_size>total:
        raise ValueError("invalid Android DTBO header or count")
    for n in range(count):
        p=entry_off+n*entry_size
        length,ofs,id,rev,*custom=struct.unpack_from("<8I",raw,p)
        if length<40 or ofs+length>total:raise ValueError("invalid DTBO entry "+str(n))
        blob=raw[ofs:ofs+length]
        yield n,{"index":n,"dt_size":length,"dt_offset":ofs,"id":hex(id),
                 "rev":hex(rev),"custom":[hex(v) for v in custom],
                 "dtbo_version":version,"page_size":page_size},blob
def extract_boot(raw):
    if raw[:8]!=b"ANDROID!" or len(raw)<2048 or u32(raw,40,False)!=2:
        raise ValueError("expected Android boot header v2")
    page=u32(raw,36,False); k=u32(raw,8,False); ram=u32(raw,16,False)
    second=u32(raw,24,False); dtbo=u32(raw,1632,False);dtb_size=u32(raw,1648,False)
    if not page or page&(page-1):raise ValueError("bad page size")
    align=lambda n:(n+page-1)//page*page
    # First page includes the boot header, then kernel, ramdisk, second, recovery DTBO, DTB.
    pos=page+align(k)+align(ram)+align(second)+align(dtbo)
    if not dtb_size or pos+dtb_size>len(raw):
        raise ValueError("invalid embedded DTB size/offset")
    return raw[pos:pos+dtb_size],dtbo
def dump_one(name,data,outdir):
    tree=fdt(data)
    safe=name.replace("/","_")
    (outdir/(safe+".dtb")).write_bytes(data)
    info={"sha256":digest(data),"size":len(data),
          "ramoops":suspicious(tree),"nodes":len(tree),
          "reserved_memory_paths":[p for p in tree if p.startswith("/reserved-memory/") and
                                   "b1b00000" in p.lower()]}
    if shutil_which("dtc"):
        out=outdir/(safe+".dts")
        p=subprocess.run(["dtc","-q","-I","dtb","-O","dts","-o",str(out),str(outdir/(safe+".dtb"))],
                         capture_output=True,text=True)
        info["dtc_rc"]=p.returncode
        if p.returncode:info["dtc_stderr"]=p.stderr[-500:]
    return info
def shutil_which(n):
    import shutil
    return shutil.which(n)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--boot",type=Path)
    p.add_argument("--dtbo",type=Path)
    p.add_argument("--live",type=Path)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    if not (a.boot or a.dtbo or a.live):p.error("supply --boot, --dtbo and/or --live")
    a.out.mkdir(parents=True,exist_ok=True)
    report={}
    if a.boot:
        raw=a.boot.read_bytes();dtb,embedded_dtbo=extract_boot(raw)
        report["boot"]={"image_sha256":digest(raw),"embedded_recovery_dtbo_bytes":embedded_dtbo,
                        **dump_one("boot-embedded",dtb,a.out)}
    if a.dtbo:
        raw=a.dtbo.read_bytes()
        info={"raw_sha256":digest(raw),"raw_bytes":len(raw),"entries":[]}
        for idx,entry,blob in dtbo_images(raw):
            entry["fdt"]=dump_one("dtbo-entry-"+str(idx),blob,a.out)
            info["entries"].append(entry)
        report["dtbo_partition"]=info
    if a.live:
        raw=a.live.read_bytes()
        report["live_fdt"]=dump_one("live-device",raw,a.out)
    report["interpretation"]="Only the partition dump read from /dev/block/by-name/dtbo identifies the flashed DTBO. No boot.img artifact can prove that identity."
    if "live_fdt" in report and "boot" in report:
        b={r["path"] for r in report["boot"]["ramoops"]}
        l={r["path"] for r in report["live_fdt"]["ramoops"]}
        report["live_only_ramoops_paths"]=sorted(l-b)
        report["boot_only_ramoops_paths"]=sorted(b-l)
    (a.out/"p461-dtbo-provenance.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__":main()
