from pathlib import Path
import struct
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'examples'


def _lp(text: str)->bytes:
    raw=text.encode('latin1');
    if len(raw)>240: raise ValueError(text)
    return bytes([len(raw)])+raw


def _rpk_channel(st,name,desc,timer='Timer_20sps'):
    return b'\x43\x09\x02\x00'+_lp(st)+_lp(name)+_lp(desc)+_lp('0.0')+_lp(timer)+b'\x00'*12


def _rpk_buffer(values):
    values=np.asarray(values,dtype='<f4'); n=len(values)
    return bytes([12])+b'ScaledBuffer'+struct.pack('<4I',n,0,n,1)+values.tobytes()


def write_racepak(path: Path):
    hz=20.0; t=np.arange(0,8.0,1/hz)
    # Deliberately simple synthetic drag pass. It exists to exercise native import + plotting,
    # not as a vehicle-performance reference.
    rpm=np.where(t<0.4, 2200+120*t, 5000+850*np.minimum(t-0.4,3.0))
    rpm=np.minimum(rpm,7800-120*np.sin(t*5))
    ds=np.maximum(0,(t-0.45))*410
    mph=np.clip(np.maximum(0,t-0.45)**0.72*58,0,195)
    g=np.where(t<0.45,0.0,np.clip(2.1-0.19*(t-0.45),0.65,2.1))
    tps=np.where(t<0.35,18.0,100.0)
    channels=[
        ('RPM','ENGINE RPM','ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]',rpm),
        ('RPM','DRIVE SHAFT','ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]',ds),
        ('MPH','MPH','ScaledBuffer: (0=>0,1=>1) [(0,250),%-5.1lf,MPH]',mph),
        ('G','G_METER','ScaledBuffer: (0=>0,1=>1) [(-3,3),%-5.2lf,G]',g),
        ('PCT','TPS','ScaledBuffer: (0=>0,1=>1) [(0,100),%-5.1lf,%]',tps),
    ]
    raw=b'\\\x07'+b'\x00'*254
    for st,name,desc,_ in channels: raw+=_rpk_channel(st,name,desc)
    raw+=b'\x00'*96
    for *_,vals in channels: raw+=_rpk_buffer(vals)
    path.write_bytes(raw)



def write_maxxecu(path: Path):
    t=np.arange(0,5.0,0.02)
    rpm=np.clip(2800+1250*np.maximum(t-0.2,0),2800,8200)
    speed=np.clip(68*np.maximum(t-0.25,0)**0.72,0,300)
    tps=np.where(t<0.18,22.0,100.0)
    boost=np.where(t<0.3,0.0,np.clip((t-0.3)*18,0,22))
    lines=['Time [s]\tEngine RPM [rpm]\tVehicle Speed [km/h]\tThrottle [%]\tBoost [psi]']
    for row in zip(t,rpm,speed,tps,boost):
        lines.append('\t'.join(f'{v:.6g}' for v in row))
    path.write_text('\n'.join(lines)+'\n')

def _putstr(blob,off,n,txt):
    b=txt.encode('latin1')[:n]; blob[off:off+len(b)]=b
    if len(b)<n: blob[off+len(b)]=0


def write_motec(path: Path):
    # Structurally realistic synthetic M1-family LD log used for native-import verification.
    t100=np.arange(0,4.01,0.01); t50=np.arange(0,4.02,0.02); t10=np.arange(0,4.1,0.1)
    channels=[
        ('Engine Speed','RPM','rpm',100,0x07,4,0,1,1,0,np.asarray(3200+1100*np.minimum(t100,3.8),dtype='<f4')),
        ('Ground Speed','','km/h',100,0x07,4,0,1,1,0,np.asarray(np.clip(52*np.maximum(t100-0.2,0)**0.70,0,310),dtype='<f4')),
        ('Engine Power','','kW',100,0x07,4,0,1,1,0,np.asarray(220+80*np.sin(np.clip(t100,0,3.8)/3.8*np.pi),dtype='<f4')),
        ('Throttle Pos','%','',100,0x07,4,0,1,1,0,np.asarray(np.where(t100<0.18,20,100),dtype='<f4')),
        ('Long Accel','','g',50,0x07,4,0,1,1,0,np.asarray(np.clip(2.0-0.28*np.maximum(t50-0.25,0),0.6,2.0),dtype='<f4')),
        ('GPS Latitude','','deg',10,0x08,8,0,1,1,0,np.asarray(36.56+0.00002*np.arange(len(t10)),dtype='<f8')),
    ]
    header_size=1800; chan_size=212; first_meta=header_size; record_count=len(channels)+1
    data_start=first_meta+chan_size*record_count
    blob=bytearray(data_start+sum(c[-1].nbytes for c in channels)+64)
    struct.pack_into('<I',blob,0,64); struct.pack_into('<I',blob,8,first_meta); struct.pack_into('<I',blob,12,data_start)
    struct.pack_into('<I',blob,36,0); struct.pack_into('<I',blob,70,12345); blob[74:82]=b'M1DEMO\x00\x00'; struct.pack_into('<H',blob,82,123)
    # Deliberately incorrect header count verifies linked-list traversal.
    struct.pack_into('<I',blob,86,99)
    _putstr(blob,94,16,'09/12/2026'); _putstr(blob,126,16,'20:00:00'); _putstr(blob,158,64,'NHRA Velocity Demo')
    _putstr(blob,222,64,'Synthetic Drag Vehicle'); _putstr(blob,350,64,'Demo Track'); _putstr(blob,1572,64,'Generated native-import validation file')
    pos=data_start
    for i,(name,short,unit,rate,dtype_a,dtype_size,shift,mul,scale,dec,vals) in enumerate(channels):
        addr=first_meta+i*chan_size; next_addr=first_meta+(i+1)*chan_size; prev_addr=first_meta+(i-1)*chan_size if i else 0
        struct.pack_into('<IIIIHHHHhhhh',blob,addr,prev_addr,next_addr,pos,len(vals),0x2EE1+i,dtype_a,dtype_size,rate,shift,mul,scale,dec)
        _putstr(blob,addr+32,32,name); _putstr(blob,addr+64,8,short); _putstr(blob,addr+72,12,unit)
        raw=vals.tobytes(); blob[pos:pos+len(raw)]=raw; pos+=len(raw)
    term=first_meta+len(channels)*chan_size; prev=first_meta+(len(channels)-1)*chan_size
    struct.pack_into('<IIIIHHHHhhhh',blob,term,prev,0,0,0,0,0x03,2,0,0,1,1,0)
    path.write_bytes(blob)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    write_racepak(OUT/'native_demo_racepak.rpk')
    write_motec(OUT/'native_demo_motec.ld')
    write_maxxecu(OUT/'native_demo_maxxecu.MaxxECU-log')
    print('wrote',OUT/'native_demo_racepak.rpk')
    print('wrote',OUT/'native_demo_motec.ld')
    print('wrote',OUT/'native_demo_maxxecu.MaxxECU-log')
