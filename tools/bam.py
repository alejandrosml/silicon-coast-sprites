# bam.py - lecture/ecriture BAM V1 / BAMC (Silicon Coast, MIT)
import struct, zlib, os, ctypes
import numpy as np

_lib = None
try:
    _here = os.path.dirname(os.path.abspath(__file__))
    for _n in ('libbamrle.so', 'libbamrle.dylib'):
        if os.path.exists(os.path.join(_here, _n)):
            _lib = ctypes.CDLL(os.path.join(_here, _n))
            _lib.rle_decode.restype = ctypes.c_long
            _lib.rle_decode.argtypes = [ctypes.c_char_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_long, ctypes.c_ubyte]
            break
except OSError:
    _lib = None

def rle_decode(data, o, n, t):
    """decode n pixels RLE a partir de l'offset o (bibliotheque C si presente, sinon Python)."""
    pix = np.empty(n, dtype=np.uint8)
    if _lib is not None:
        mv = memoryview(data)[o:]
        buf = bytes(mv[:min(len(mv), 2 * n + 2)])
        r = _lib.rle_decode(buf, len(buf), pix.ctypes.data, n, t)
        if r < 0:
            raise ValueError('RLE tronque')
        return pix
    j = 0; p = o
    while j < n:
        v = data[p]; p += 1
        if v == t:
            r = data[p] + 1; p += 1
            pix[j:j + r] = t; j += r
        else:
            pix[j] = v; j += 1
    return pix[:n]

class Frame:
    __slots__=('w','h','cx','cy','pix','rle')
    def __init__(s,w,h,cx,cy,pix,rle=True):
        s.w,s.h,s.cx,s.cy,s.pix,s.rle=w,h,cx,cy,pix,rle

class BamV1:
    def __init__(s):
        s.frames=[]; s.cycles=[]; s.palette=None; s.tidx=0; s.lookup=[]
    @staticmethod
    def load(data):
        if data[:4]==b'BAMC':
            ulen=struct.unpack('<I',data[8:12])[0]
            data=zlib.decompress(data[12:]); assert len(data)==ulen
        assert data[:8]==b'BAM V1  ', data[:8]
        b=BamV1()
        nf,nc,b.tidx,ofr,opal,olk=struct.unpack('<HBBIII',data[8:0x18])
        b.palette=np.frombuffer(data[opal:opal+1024],dtype=np.uint8).reshape(256,4).copy()
        cyc=[]
        oc=ofr+12*nf
        maxlk=0
        for i in range(nc):
            cnt,start=struct.unpack('<HH',data[oc+4*i:oc+4*i+4])
            cyc.append((cnt,start)); maxlk=max(maxlk,start+cnt)
        b.lookup=list(struct.unpack('<%dH'%maxlk,data[olk:olk+2*maxlk])) if maxlk else []
        b.cycles=cyc
        cache={}
        for i in range(nf):
            w,h,cx,cy,off=struct.unpack('<HHhhI',data[ofr+12*i:ofr+12*i+12])
            raw=not (off&0x80000000)==0
            o=off&0x7fffffff
            key=(o,w,h,raw)
            if key in cache: pix=cache[key]
            else:
                n=w*h
                if raw or n==0:
                    pix=np.frombuffer(data[o:o+n],dtype=np.uint8).copy()
                else:
                    pix=rle_decode(data,o,n,b.tidx)
                pix=pix.reshape(h,w) if n else np.zeros((h,w),np.uint8)
                cache[key]=pix
            b.frames.append(Frame(w,h,cx,cy,pix,not raw))
        return b
    def dump(s, compress=True, level=9):
        nf=len(s.frames); nc=len(s.cycles)
        ofr=0x18; ocyc=ofr+12*nf; opal=ocyc+4*nc; olk=opal+1024; odat=olk+2*len(s.lookup)
        datas=[]; offs=[]; cur=odat; cache={}
        for f in s.frames:
            key=id(f.pix)
            if key in cache:
                offs.append(cache[key]); continue
            enc=rle_encode_np(f.pix.reshape(-1),s.tidx) if f.rle else f.pix.tobytes()
            off=cur | (0 if f.rle else 0x80000000)
            cache[key]=off; offs.append(off); datas.append(enc); cur+=len(enc)
        out=bytearray()
        out+=b'BAM V1  '+struct.pack('<HBBIII',nf,nc,s.tidx,ofr,opal,olk)
        for f,o in zip(s.frames,offs):
            out+=struct.pack('<HHhhI',f.w,f.h,f.cx,f.cy,o)
        for cnt,start in s.cycles: out+=struct.pack('<HH',cnt,start)
        out+=s.palette.astype(np.uint8).tobytes()
        out+=struct.pack('<%dH'%len(s.lookup),*s.lookup)
        for d in datas: out+=d
        out=bytes(out)
        if compress:
            return b'BAMCV1  '+struct.pack('<I',len(out))+zlib.compress(out,level)
        return out

def rle_encode(a,t):
    a=np.asarray(a,dtype=np.uint8); n=len(a); out=bytearray(); i=0
    while i<n:
        v=int(a[i])
        if v==t:
            j=i
            while j<n and a[j]==t and j-i<256: j+=1
            out.append(t); out.append(j-i-1); i=j
        else:
            out.append(v); i+=1
    return bytes(out)

def rle_encode_np(a, t):
    """meme sortie que rle_encode, vectorise (numpy)."""
    a = np.ascontiguousarray(a, dtype=np.uint8).ravel()
    n = a.size
    if n == 0:
        return b''
    ist = a == t
    change = np.flatnonzero(ist[1:] != ist[:-1]) + 1
    starts = np.concatenate(([0], change)); ends = np.concatenate((change, [n]))
    lens = ends - starts
    trans = ist[starts]
    nch = np.where(trans, (lens + 255) // 256, 0)
    outlen = np.where(trans, 2 * nch, lens)
    offs = np.concatenate(([0], np.cumsum(outlen)[:-1]))
    out = np.empty(int(outlen.sum()), np.uint8)
    op = ~trans
    if op.any():
        rid = np.repeat(np.flatnonzero(op), lens[op])
        p = np.flatnonzero(~ist)
        out[offs[rid] + p - starts[rid]] = a[p]
    tr = np.flatnonzero(trans)
    if tr.size:
        nc = nch[tr]
        rid = np.repeat(tr, nc)
        first = np.cumsum(nc) - nc
        j = np.arange(int(nc.sum())) - np.repeat(first, nc)
        pos = offs[rid] + 2 * j
        out[pos] = t
        out[pos + 1] = (np.minimum(256, lens[rid] - 256 * j) - 1).astype(np.uint8)
    return out.tobytes()

def rle_size(a, t):
    """taille de l'encodage RLE sans l'ecrire."""
    a = np.asarray(a).ravel()
    if a.size == 0:
        return 0
    ist = a == t
    change = np.flatnonzero(ist[1:] != ist[:-1]) + 1
    starts = np.concatenate(([0], change)); ends = np.concatenate((change, [a.size]))
    lens = ends - starts
    trans = ist[starts]
    return int(np.where(trans, 2 * ((lens + 255) // 256), lens).sum())
