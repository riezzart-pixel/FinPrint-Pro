"""FinPrint Pro API: berbagi database SQLite yang sama dengan aplikasi Streamlit Windows."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib, secrets, sqlite3, os
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DB = Path(os.getenv('FINPRINT_DB', str(BASE / 'finprint_pro.db')))
MOBILE = BASE / 'mobile'
app = FastAPI(title='FinPrint Pro Sync API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
SESSIONS = {}
SESSION_HOURS = 12

@app.on_event('startup')
def enable_wal():
    if DB.exists():
        with db() as c: c.execute('PRAGMA journal_mode=WAL')

def db():
    con = sqlite3.connect(str(DB), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=30000')
    return con

def sha(p): return hashlib.sha256(p.encode('utf-8')).hexdigest()
def rows(sql, args=()):
    with db() as c: return [dict(r) for r in c.execute(sql, args).fetchall()]
def one(sql,args=()):
    r=rows(sql,args); return r[0] if r else None

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
class TransactionIn(BaseModel):
    tanggal: str
    jenis: str
    kategori: str
    jumlah: float = Field(gt=0)
    keterangan: str = ''
class OrderIn(BaseModel):
    tanggal: str
    waktu: str = ''
    jenis_cetak: str
    ukuran: str = ''
    jumlah: int = Field(ge=1)
    luas_total: float = Field(ge=0)
    bahan_id: Optional[int] = None
    harga_bahan_satuan: float = Field(ge=0)
    harga_tinta_satuan: float = Field(ge=0)
    harga_laminasi_satuan: float = Field(ge=0)
    harga_potong_satuan: float = Field(ge=0)
    harga_packing_satuan: float = Field(ge=0)
    harga_finishing_satuan: float = Field(ge=0)
    pakai_laminasi: bool = False
    pakai_potong: bool = False
    pakai_packing: bool = False
    pakai_finishing: bool = False
    margin: float = Field(ge=0, le=500)
    harga_jual: Optional[float] = Field(default=None, ge=0)
    keterangan: str = ''

@app.get('/api/health')
def health():
    return {'ok': True, 'app':'FinPrint Pro', 'database':DB.name, 'time':datetime.now().astimezone().isoformat()}

@app.post('/api/login')
def login(data: Login):
    u=one('SELECT id,username,password,role,nama FROM users WHERE username=?',(data.username,))
    if not u or not secrets.compare_digest(str(u['password']),sha(data.password)):
        raise HTTPException(401,'Username atau password salah.')
    token=secrets.token_urlsafe(36)
    SESSIONS[token]={'username':u['username'],'role':u['role'],'nama':u['nama'],'expires':datetime.now(timezone.utc)+timedelta(hours=SESSION_HOURS)}
    return {'token':token,'username':u['username'],'role':u['role'],'nama':u['nama'],'expires_in':SESSION_HOURS*3600}

def current(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '): raise HTTPException(401,'Silakan login kembali.')
    token=authorization[7:]; s=SESSIONS.get(token)
    if not s or s['expires'] < datetime.now(timezone.utc):
        SESSIONS.pop(token,None); raise HTTPException(401,'Sesi berakhir. Silakan login kembali.')
    return s

@app.post('/api/logout')
def logout(user=Depends(current), authorization: str=Header(default='')):
    SESSIONS.pop(authorization[7:],None); return {'ok':True}

@app.get('/api/dashboard')
def dashboard(user=Depends(current)):
    income=one("SELECT COALESCE(SUM(jumlah),0) n FROM transaksi WHERE jenis='Pemasukan'")['n']
    expense=one("SELECT COALESCE(SUM(jumlah),0) n FROM transaksi WHERE jenis='Pengeluaran'")['n']
    count=one('SELECT COUNT(*) n FROM pesanan')['n']
    orders=rows('SELECT id,tanggal,waktu,jenis_cetak,ukuran,jumlah,harga_jual,estimasi_laba,status,keterangan FROM pesanan ORDER BY id DESC LIMIT 12')
    return {'pemasukan':income,'pengeluaran':expense,'saldo':income-expense,'jumlah_pesanan':count,'pesanan_terbaru':orders}

@app.get('/api/materials')
def materials(user=Depends(current)):
    return {'items':rows('SELECT id,nama,satuan,harga,keterangan FROM bahan ORDER BY nama'), 'settings':one('SELECT * FROM pengaturan WHERE id=1') or {}}

@app.get('/api/transactions')
def transactions(limit:int=100,user=Depends(current)):
    limit=max(1,min(limit,500)); return {'items':rows('SELECT * FROM transaksi ORDER BY id DESC LIMIT ?', (limit,))}

@app.post('/api/transactions')
def add_transaction(x:TransactionIn,user=Depends(current)):
    if x.jenis not in ('Pemasukan','Pengeluaran'): raise HTTPException(400,'Jenis transaksi tidak valid.')
    with db() as c:
        cur=c.execute('INSERT INTO transaksi(tanggal,jenis,kategori,jumlah,keterangan,created_by) VALUES(?,?,?,?,?,?)',(x.tanggal,x.jenis,x.kategori,x.jumlah,x.keterangan,user['username']))
        new_id=cur.lastrowid
    return {'ok':True,'id':new_id}

@app.get('/api/orders')
def orders(limit:int=100,user=Depends(current)):
    limit=max(1,min(limit,500)); return {'items':rows('SELECT * FROM pesanan ORDER BY id DESC LIMIT ?', (limit,))}

@app.post('/api/orders')
def add_order(x:OrderIn,user=Depends(current)):
    if x.bahan_id:
        mat=one('SELECT nama,satuan FROM bahan WHERE id=?',(x.bahan_id,))
        if not mat: raise HTTPException(400,'Bahan tidak ditemukan.')
        unit=mat['satuan'].lower()
    else:
        unit='per m2'
    if 'lembar' in unit: material=x.jumlah*x.harga_bahan_satuan
    elif 'meter' in unit and 'm²' not in unit: material=x.luas_total*x.harga_bahan_satuan
    else: material=x.luas_total*x.harga_bahan_satuan
    tinta=x.luas_total*x.harga_tinta_satuan
    lam=x.luas_total*x.harga_laminasi_satuan if x.pakai_laminasi else 0
    cut=x.jumlah*x.harga_potong_satuan if x.pakai_potong else 0
    pack=x.jumlah*x.harga_packing_satuan if x.pakai_packing else 0
    finish=x.jumlah*x.harga_finishing_satuan if x.pakai_finishing else 0
    hpp=material+tinta+lam+cut+pack+finish
    price=float(x.harga_jual) if x.harga_jual is not None else round(hpp*(1+x.margin/100))
    data=(x.tanggal,x.waktu,x.jenis_cetak,x.ukuran,x.jumlah,x.luas_total,material,tinta,lam,cut,pack,finish,hpp,x.margin,price,price-hpp,x.keterangan,int(x.pakai_laminasi),int(x.pakai_potong),int(x.pakai_packing),int(x.pakai_finishing),x.harga_bahan_satuan,x.harga_tinta_satuan,x.harga_laminasi_satuan,x.harga_potong_satuan,x.harga_packing_satuan,x.harga_finishing_satuan)
    fields='tanggal,waktu,jenis_cetak,ukuran,jumlah,luas_total,biaya_bahan,biaya_tinta,biaya_laminasi,biaya_potong,biaya_packing,biaya_finishing,total_hpp,margin,harga_jual,estimasi_laba,keterangan,pakai_laminasi,pakai_potong,pakai_packing,pakai_finishing,harga_bahan_satuan,harga_tinta_satuan,harga_laminasi_satuan,harga_potong_satuan,harga_packing_satuan,harga_finishing_satuan'
    with db() as c:
        cur=c.execute(f'INSERT INTO pesanan({fields},status) VALUES({",".join(["?"]*len(data))},?)',data+('Baru',)); oid=cur.lastrowid
    return {'ok':True,'id':oid,'total_hpp':hpp,'harga_jual':price,'estimasi_laba':price-hpp}

@app.patch('/api/orders/{order_id}/status')
def update_status(order_id:int,status:str,user=Depends(current)):
    if user['role']!='admin': raise HTTPException(403,'Hanya admin yang dapat mengubah status.')
    if status not in ('Baru','Proses','Selesai','Batal'): raise HTTPException(400,'Status tidak valid.')
    with db() as c:
        cur=c.execute('UPDATE pesanan SET status=? WHERE id=?',(status,order_id))
        if cur.rowcount==0: raise HTTPException(404,'Pesanan tidak ditemukan.')
    return {'ok':True}

@app.get('/')
def mobile_home(): return FileResponse(MOBILE/'index.html')
app.mount('/mobile',StaticFiles(directory=str(MOBILE),html=True),name='mobile')
