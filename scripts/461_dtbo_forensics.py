#!/usr/bin/env python3
"""P461: inspect the EXACT flashed DTBO image, Android DTBO tables,
and the live FDT. Read only: never flash or modify a partition.
Uses dtc, if available, to emit one .dts per DTBO entry.
"""
import argparse, hashlib, json, shutil, struct, subprocess
from pathlib import Path

MAGIC=0xD7B7AB1E
FDT=b"\xd0\x0d\xfe\xed"

def sha(b): return hashlib.sha256(b).hexdigest()

def fdt_props(blob):
    if len(blob)<40 or blob[:4]!=FDT: raise RuntimeError("not FDT")
    _,total,st,strings,_,_,_,_,sz_strings,sz_struct=struct.unpack_from(">10I",blob)
    if total>len(blob) or st+sz_struct>total or strings+sz_strings>total:
        raise RuntimeError("invalid FDT bounds")
    off=st; stack=[]; result=[]; finished=False
    while off+4<=st+sz_struct:
        token=struct.unpack_from(">I",blob,off)[0]; off+=4
        if token==1:
            end=blob.find(b"\0",off,st+sz_struct)
            if end<0:raise RuntimeError("unterminated FDT node")
            name=blob[off:end].decode("utf8","replace")
            stack.append(name); off=(end+4)&~3
        elif token==2:
            if not stack:raise RuntimeError("FDT stack underflow")
            stack.pop()
        elif token==3:
            if off+8>st+sz_struct:raise RuntimeError("bad FDT property")
            length,nameoff=struct.unpack_from(">II",blob,off); off+=8
            data=blob[off:off+length];off+=(length+3)&~3
            if nameoff>=sz_strings:raise RuntimeError("bad string offset")
            end=blob.find(b"\0",strings+nameoff,strings+sz_strings)
            if end<0:raise RuntimeError("bad FDT string")
            key=blob[strings+nameoff:end].decode("ascii","replace")
            node="/" + "/".join(stack[1:])
            if key in ("compatible","target-path","status"):
                value=data.rstrip(b"\0").decode("utf8","replace")
            elif key in ("ecc-size","reg","phandle","linux,phandle") and len(data)%4==0:
                value=["0x%08x"%v for v in struct.unpack(">%dI"%(len(data)//4),data)]
            else:
                value="0x"+data.hex()[:100]
            result.append({"node":node,"property":key,"value":value})
        elif token==4:pass
        elif token==9:
            if stack:raise RuntimeError("FDT_END before END_NODE")
            finished=True;break
        else:raise RuntimeError("invalid FDT token "+str(token))
    if not finished:raise RuntimeError("no FDT_END")
    return result

def describe_fdt(blob):
    props=fdt_props(blob)
    names={x["node"] for x in props}
    selected=set()
    for p in props:
        if ("ramoops" in p["node"].lower() or
            "ramoops" in str(p["value"]).lower() or
            "b1b00000" in str(p["value"]).lower() or
            p["property"]=="target-path" and "reserved-memory" in str(p["value"])):
            selected.add(p["node"])
    return {
      "sha256":sha(blob),
      "size":len(blob),
      "ramoops_or_reserved_memory_fragments":[
        {"path":n,"properties":[p for p in props if p["node"]==n]}
        for n in sorted(selected)],
      "ramoops_nodes":[n for n in sorted(names) if "ramoops" in n.lower()]
    }

def dtbo_entries(data):
    if len(data)<32:raise RuntimeError("DTBO partition image too short")
    if data[:4]==FDT:
        total=struct.unpack_from(">I",data,4)[0]
        if total>len(data):raise RuntimeError("raw FDT overrun")
        return [{"index":0,"offset":0,"size":total,"data":data[:total],
                 "format":"raw-fdt"}]
    # Android libufdt mkdtboimg.py encodes DTBO tables in BIG-endian.
    hdr=struct.unpack_from(">8I",data)
    magic,total,headsz,entsz,count,offset,page,version=hdr
    if magic!=MAGIC:raise RuntimeError("DTBO magic not Android BIG-endian table or raw FDT: "+data[:16].hex())
    if total>len(data) or headsz<32 or entsz<32 or count>128 or offset<headsz:
        raise RuntimeError("malformed Android DTBO table header "+repr(hdr))
    if offset+count*entsz>total:raise RuntimeError("DTBO entries overflow")
    out=[]
    for idx in range(count):
        e=offset+idx*entsz
        size,pos,ident,rev,*custom=struct.unpack_from(">8I",data,e)
        if pos<32 or size<40 or pos+size>total:raise RuntimeError("bad DTBO entry "+str(idx))
        blob=data[pos:pos+size]
        if blob[:4]!=FDT:raise RuntimeError("DTBO entry is not FDT: "+str(idx))
        if struct.unpack_from(">I",blob,4)[0]!=len(blob):
            raise RuntimeError("DTBO entry size disagreement "+str(idx))
        out.append({"index":idx,"offset":pos,"size":size,
                    "id":ident,"rev":rev,"custom":custom,"data":blob,
                    "format":"android-dtbo-v"+str(version)})
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dtbo",type=Path,required=True,help="Raw dd of /dev/block/by-name/dtbo (NOT boot.img)")
    p.add_argument("--boot-dtb",type=Path,help="Extracted final boot.img FDT for comparison")
    p.add_argument("--live-dtb",type=Path,help="Snapshot of /sys/firmware/fdt AFTER bootloader fixes")
    p.add_argument("--identity",type=Path,help="partition-identity.txt from the read-only capture")
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    src=args.dtbo.read_bytes()
    identity = args.identity.read_text(errors="replace") if args.identity else ""
    reported_index = None
    for line in identity.splitlines():
        if line.startswith("ro.boot.dtbo_idx="):
            value=line.partition("=")[2].strip()
            if value:
                reported_index=int(value,0)
    entries=dtbo_entries(src)
    report={"dtbo_path":str(args.dtbo),"dtbo_sha256":sha(src),
            "partition_identity":identity,
            "bootloader_reported_dtbo_idx":reported_index,
            "dtbo_partition_bytes":len(src),"dtbo_entries":[]}
    for e in entries:
        name=f"dtbo-entry-{e['index']:02d}"
        blob=e.pop("data")
        (args.out/(name+".dtb")).write_bytes(blob)
        v={**e,**describe_fdt(blob)}
        report["dtbo_entries"].append(v)
        if shutil.which("dtc"):
            x=subprocess.run(["dtc","-I","dtb","-O","dts","-o",
                str(args.out/(name+".dts")),str(args.out/(name+".dtb"))],
                capture_output=True,text=True)
            (args.out/(name+".dtc.log")).write_text(x.stderr)
            if x.returncode:raise RuntimeError("dtc failed for "+name+": "+x.stderr[-300:])
    for label,file in (("packaged_boot",args.boot_dtb),("live_runtime",args.live_dtb)):
        if file:
            blob=file.read_bytes()
            report[label] = describe_fdt(blob)
    if reported_index is not None:
        if not 0 <= reported_index < len(entries):
            raise RuntimeError("bootloader-reported DTBO index outside captured image")
        report["selected_dtbo_entry"] = reported_index
    else:
        report["selected_dtbo_entry"] = "UNPROVEN: no bootloader index; table id/rev alone do not establish selection"
    phantom="a52-ramoops-reserved@b1b00000"
    suspect=[x["index"] for x in report["dtbo_entries"] if
             any(phantom in n.lower() for n in x["ramoops_nodes"])]
    report["dtbo_entries_containing_phantom"] = suspect
    live=report.get("live_runtime")
    boot=report.get("packaged_boot")
    def has_phantom(tree):
        return bool(tree and any(phantom in n.lower() for n in tree["ramoops_nodes"]))
    report["evidence"]={
      "packaged_boot_phantom":has_phantom(boot),
      "live_fdt_phantom":has_phantom(live),
      "any_dtbo_entry_phantom":bool(suspect),
      "reported_index_contains_phantom":reported_index in suspect if reported_index is not None else None}
    if has_phantom(boot):
        report["source_of_any_runtime_overlap"]="Packaged boot DTB already contains phantom; investigate boot build first"
    elif reported_index in suspect and reported_index is not None and has_phantom(live):
        report["source_of_any_runtime_overlap"]="Captured selected DTBO contains phantom and live FDT contains it"
    elif not suspect and has_phantom(live) and boot is not None:
        report["source_of_any_runtime_overlap"]="Not in supplied boot DTB or captured DTBO entries; investigate different flashed boot, bootloader fix-up, or kernel mutation"
    else:
        report["source_of_any_runtime_overlap"]="UNPROVEN: need known boot DTB, live FDT and selected DTBO index for attribution"
    (args.out/"dtbo-forensics.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("P461 DTBO FORENSICS",report["dtbo_sha256"],
          "entries",len(entries),"live_fdt",bool(args.live_dtb),
          "report",args.out/"dtbo-forensics.json")
if __name__=="__main__":
    main()
