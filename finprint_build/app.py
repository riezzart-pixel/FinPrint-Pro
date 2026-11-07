import streamlit as st
import pandas as pd
import sqlite3
import datetime as dt
import hashlib
import os
from io import BytesIO
from fpdf import FPDF
import plotly.graph_objects as go

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "finprint_pro.db")
os.makedirs(os.path.join(APP_DIR, "bukti_transaksi"), exist_ok=True)

st.set_page_config(page_title="FinPrint Pro", page_icon="🖨️", layout="wide")

st.markdown("""
<style>
.stApp {background:linear-gradient(135deg,#0b1220,#17243a); color:#e5edf8}
[data-testid="stSidebar"] {background:#111c2e}
h1,h2,h3 {color:#f4f7fb}
[data-testid="stMetric"] {background:#1c2c43;border:1px solid #31445f;padding:14px;border-radius:14px}
.stButton>button,.stDownloadButton>button {border-radius:10px;font-weight:600}
div[data-baseweb="input"] input,textarea {border-radius:8px}
.small-muted {color:#a9b8cc;font-size:.9rem}
</style>
""", unsafe_allow_html=True)

def money(v):
    return f"Rp {float(v or 0):,.0f}".replace(",", ".")

def hash_password(p):
    return hashlib.sha256(p.encode("utf-8")).hexdigest()

def conn_db():
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con

def columns(c, table):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}

def add_column(c, table, name, definition):
    if name not in columns(c, table):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

def init_db():
    with conn_db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        c = con.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE,
            password TEXT, role TEXT, nama TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS transaksi(
            id INTEGER PRIMARY KEY AUTOINCREMENT, tanggal TEXT, jenis TEXT,
            kategori TEXT, jumlah REAL, keterangan TEXT, created_by TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS target(
            id INTEGER PRIMARY KEY AUTOINCREMENT, bulan TEXT UNIQUE, target_omzet REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS bahan(
            id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT NOT NULL,
            satuan TEXT NOT NULL, harga REAL NOT NULL, keterangan TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS pengaturan(
            id INTEGER PRIMARY KEY CHECK(id=1), tinta_per_m2 REAL DEFAULT 8000,
            laminasi_per_m2 REAL DEFAULT 12000, potong_per_pcs REAL DEFAULT 500,
            packing_per_pcs REAL DEFAULT 500, finishing_per_pcs REAL DEFAULT 1000,
            margin_default REAL DEFAULT 40)""")
        c.execute("""CREATE TABLE IF NOT EXISTS pesanan(
            id INTEGER PRIMARY KEY AUTOINCREMENT, tanggal TEXT, jenis_cetak TEXT,
            ukuran TEXT, jumlah INTEGER, luas_total REAL, biaya_bahan REAL,
            biaya_tinta REAL, biaya_laminasi REAL DEFAULT 0, biaya_potong REAL DEFAULT 0,
            biaya_packing REAL DEFAULT 0, biaya_finishing REAL DEFAULT 0,
            total_hpp REAL, margin REAL, harga_jual REAL, estimasi_laba REAL,
            keterangan TEXT, status TEXT DEFAULT 'Baru')""")
        # Safe schema upgrades for databases made by earlier FinPrint versions.
        add_column(c, "pengaturan", "packing_per_pcs", "REAL DEFAULT 500")
        add_column(c, "pesanan", "waktu", "TEXT DEFAULT ''")
        add_column(c, "pesanan", "pakai_laminasi", "INTEGER DEFAULT 0")
        add_column(c, "pesanan", "pakai_potong", "INTEGER DEFAULT 0")
        add_column(c, "pesanan", "pakai_packing", "INTEGER DEFAULT 0")
        add_column(c, "pesanan", "pakai_finishing", "INTEGER DEFAULT 0")
        add_column(c, "pesanan", "harga_bahan_satuan", "REAL DEFAULT 0")
        add_column(c, "pesanan", "harga_tinta_satuan", "REAL DEFAULT 0")
        add_column(c, "pesanan", "harga_laminasi_satuan", "REAL DEFAULT 0")
        add_column(c, "pesanan", "harga_potong_satuan", "REAL DEFAULT 0")
        add_column(c, "pesanan", "harga_packing_satuan", "REAL DEFAULT 0")
        add_column(c, "pesanan", "harga_finishing_satuan", "REAL DEFAULT 0")
        c.execute("INSERT OR IGNORE INTO pengaturan(id) VALUES(1)")
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO users(username,password,role,nama) VALUES(?,?,?,?)",
                      ("admin", hash_password("finprint123"), "admin", "Administrator"))
        c.execute("SELECT COUNT(*) FROM bahan")
        if c.fetchone()[0] == 0:
            c.executemany("INSERT INTO bahan(nama,satuan,harga,keterangan) VALUES(?,?,?,?)", [
                ("Art Paper 120gsm","Per Lembar",800,"A4"),
                ("Art Paper 260gsm","Per Lembar",2200,"A3+"),
                ("HVS 80gsm","Per Lembar",500,"A4"),
                ("Stiker Chromo","Per m²",22000,"Stiker"),
                ("Stiker Vinyl Glossy","Per m²",28000,"Outdoor"),
                ("Banner Flexi 280gsm","Per m²",18000,"Banner"),
                ("Vinyl Roll","Per Meter",35000,"Lebar 105 cm"),
            ])

def read_df(query, params=()):
    with conn_db() as con:
        return pd.read_sql_query(query, con, params=params)

def get_settings():
    return read_df("SELECT * FROM pengaturan WHERE id=1").iloc[0].to_dict()

def login_user(username, password):
    df = read_df("SELECT password,role,nama FROM users WHERE username=?", (username,))
    if not df.empty and df.iloc[0]["password"] == hash_password(password):
        return {"role": df.iloc[0]["role"], "nama": df.iloc[0]["nama"]}
    return None

def pdf_receipt(order):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "FinPrint Pro", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, "NOTA PESANAN PERCETAKAN", ln=True, align="C")
    pdf.ln(5)
    lines = [
        f"No. Pesanan: #{order['id']}",
        f"Tanggal/Jam: {order.get('tanggal','')} {order.get('waktu','')}",
        f"Customer: {order.get('keterangan') or '-'}",
        f"Jenis: {order['jenis_cetak']}",
        f"Ukuran: {order['ukuran']} | Jumlah: {order['jumlah']}",
        f"Laminasi: {'Ya' if order.get('pakai_laminasi') else 'Tidak'}",
        f"Potong: {'Ya' if order.get('pakai_potong') else 'Tidak'}",
        f"Packing: {'Ya' if order.get('pakai_packing') else 'Tidak'}",
        f"Finishing: {'Ya' if order.get('pakai_finishing') else 'Tidak'}",
    ]
    for line in lines:
        pdf.cell(0, 7, line, ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    for label, key in [("Total HPP","total_hpp"),("Harga Jual","harga_jual"),("Estimasi Laba","estimasi_laba")]:
        pdf.cell(0, 8, f"{label}: {money(order[key])}", ln=True)
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 7, "Terima kasih telah menggunakan jasa kami.", ln=True, align="C")
    return pdf

init_db()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.logged_in:
    st.markdown("<br><br>", unsafe_allow_html=True)
    left, center, right = st.columns([1,1.4,1])
    with center:
        st.title("🖨️ FinPrint Pro")
        st.caption("Sistem Manajemen Keuangan & Produksi Percetakan")
        with st.form("login"):
            username = st.text_input("Username", placeholder="Username")
            password = st.text_input("Password", type="password", placeholder="Password")
            go = st.form_submit_button("Masuk", type="primary", use_container_width=True)
        if go:
            u = login_user(username, password)
            if u:
                st.session_state.logged_in = True
                st.session_state.user = {"username": username, **u}
                st.rerun()
            else:
                st.error("Username atau password salah.")
        st.info("Login awal: **admin** / **finprint123**. Segera ubah password setelah masuk.")
    st.stop()

user = st.session_state.user
admin = user["role"] == "admin"
now = dt.datetime.now()
st.sidebar.title("🖨️ FinPrint Pro")
st.sidebar.write(f"**{user['nama']}**")
st.sidebar.caption(user["role"].upper())
st.sidebar.markdown(f"### 🕒 {now.strftime('%H:%M:%S')}")
st.sidebar.caption(now.strftime("%A, %d %B %Y"))
if st.sidebar.button("Keluar", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.user = None
    st.rerun()

menus = ["Dashboard","Transaksi Keuangan","Kalkulator Harga","Daftar Pesanan","Laporan"]
if admin:
    menus += ["Pengaturan"]
menu = st.sidebar.radio("Menu", menus)

trans = read_df("SELECT * FROM transaksi ORDER BY tanggal DESC,id DESC")
orders = read_df("SELECT * FROM pesanan ORDER BY id DESC")
materials = read_df("SELECT * FROM bahan ORDER BY nama")
settings = get_settings()
income = trans.loc[trans.jenis=="Pemasukan","jumlah"].sum() if not trans.empty else 0
expense = trans.loc[trans.jenis=="Pengeluaran","jumlah"].sum() if not trans.empty else 0

if menu == "Dashboard":
    st.title("📊 Dashboard")
    st.caption(f"Ringkasan bisnis — {now.strftime('%d-%m-%Y %H:%M:%S')}")
    a,b,c,d = st.columns(4)
    a.metric("Total Pemasukan", money(income))
    b.metric("Total Pengeluaran", money(expense))
    c.metric("Saldo", money(income-expense))
    d.metric("Total Pesanan", len(orders))
    if not trans.empty:
        t = trans.copy()
        t["tanggal"] = pd.to_datetime(t["tanggal"], errors="coerce")
        t = t[t.tanggal >= pd.Timestamp.now()-pd.Timedelta(days=30)]
        if not t.empty:
            daily = t.groupby([t.tanggal.dt.date,"jenis"])["jumlah"].sum().unstack(fill_value=0)
            fig = go.Figure()
            for col in ["Pemasukan","Pengeluaran"]:
                if col in daily:
                    fig.add_bar(x=daily.index,y=daily[col],name=col)
            fig.update_layout(title="Arus Kas 30 Hari Terakhir",barmode="group",template="plotly_dark",height=360)
            st.plotly_chart(fig,use_container_width=True)
    st.subheader("Pesanan terbaru")
    st.dataframe(orders.head(10),use_container_width=True,hide_index=True)

elif menu == "Transaksi Keuangan":
    st.title("💰 Transaksi Keuangan")
    tab1,tab2 = st.tabs(["Tambah transaksi","Riwayat"])
    with tab1:
        with st.form("transaction_form",clear_on_submit=True):
            c1,c2 = st.columns(2)
            tanggal = c1.date_input("Tanggal",dt.date.today())
            waktu = c2.time_input("Jam",dt.datetime.now().time().replace(microsecond=0))
            jenis = c1.selectbox("Jenis",["Pemasukan","Pengeluaran"])
            kategori = c2.selectbox("Kategori",["Penjualan","Bahan Baku","Operasional","Gaji","Sewa","Listrik/Internet","Lainnya"])
            jumlah = st.number_input("Jumlah (Rp)",min_value=0,step=1000)
            ket = st.text_input("Keterangan")
            save = st.form_submit_button("Simpan transaksi",type="primary")
        if save and jumlah > 0:
            with conn_db() as con:
                con.execute("INSERT INTO transaksi(tanggal,jenis,kategori,jumlah,keterangan,created_by) VALUES(?,?,?,?,?,?)",
                            (f"{tanggal} {waktu}",jenis,kategori,float(jumlah),ket,user["username"]))
            st.success("Transaksi disimpan."); st.rerun()
    with tab2:
        st.dataframe(trans,use_container_width=True,hide_index=True)
        if admin and not trans.empty:
            delid = st.number_input("ID transaksi yang dihapus",min_value=1,step=1)
            if st.button("Hapus transaksi"):
                with conn_db() as con: con.execute("DELETE FROM transaksi WHERE id=?",(int(delid),))
                st.rerun()

elif menu == "Kalkulator Harga":
    st.title("🧮 Kalkulator Harga Cetak")
    if materials.empty:
        st.warning("Tambahkan bahan di Pengaturan terlebih dahulu.")
    else:
        names = materials.nama.tolist()
        with st.form("calculator"):
            st.subheader("Data pesanan")
            c1,c2,c3 = st.columns(3)
            material_name = c1.selectbox("Bahan / jenis cetak",names)
            size = c2.text_input("Ukuran", "A4")
            qty = c3.number_input("Jumlah",min_value=1,value=1,step=1)
            c4,c5,c6 = st.columns(3)
            order_date = c4.date_input("Tanggal",dt.date.today())
            order_time = c5.time_input("Jam pesanan",dt.datetime.now().time().replace(microsecond=0))
            customer = c6.text_input("Nama customer / keterangan")
            area = st.number_input("Luas total (m²)",min_value=0.0,value=0.0625,step=0.01,format="%.4f",
                                   help="Masukkan luas total seluruh hasil cetak.")
            st.markdown("#### Pekerjaan tambahan")
            x1,x2,x3,x4 = st.columns(4)
            use_lam = x1.checkbox("Pakai laminasi")
            use_cut = x2.checkbox("Pakai potong")
            use_pack = x3.checkbox("Pakai packing")
            use_finish = x4.checkbox("Pakai finishing")
            st.markdown("#### Harga satuan (bisa diubah setiap pesanan)")
            selected = materials[materials.nama==material_name].iloc[0]
            default_material = float(selected.harga)
            p1,p2,p3 = st.columns(3)
            material_price = p1.number_input(f"Harga bahan ({selected.satuan}) Rp",min_value=0.0,value=default_material,step=500.0)
            ink_rate = p2.number_input("Tinta per m² (Rp)",min_value=0.0,value=float(settings["tinta_per_m2"]),step=500.0)
            lam_rate = p3.number_input("Laminasi per m² (Rp)",min_value=0.0,value=float(settings["laminasi_per_m2"]),step=500.0,disabled=not use_lam)
            p4,p5,p6 = st.columns(3)
            cut_rate = p4.number_input("Potong per pcs (Rp)",min_value=0.0,value=float(settings["potong_per_pcs"]),step=100.0,disabled=not use_cut)
            pack_rate = p5.number_input("Packing per pcs (Rp)",min_value=0.0,value=float(settings["packing_per_pcs"] or 0),step=100.0,disabled=not use_pack)
            finish_rate = p6.number_input("Finishing per pcs (Rp)",min_value=0.0,value=float(settings["finishing_per_pcs"]),step=100.0,disabled=not use_finish)
            margin = st.number_input("Margin keuntungan (%)",min_value=0.0,max_value=500.0,value=float(settings["margin_default"]),step=5.0)
            calc = st.form_submit_button("Hitung harga",type="primary")
        if calc:
            unit = str(selected.satuan).lower()
            if "lembar" in unit:
                material_cost = qty*material_price
            elif "meter" in unit and "m²" not in unit:
                material_cost = max(area,0)*material_price
            else:
                material_cost = area*material_price
            ink_cost = area*ink_rate
            lam_cost = area*lam_rate if use_lam else 0
            cut_cost = qty*cut_rate if use_cut else 0
            pack_cost = qty*pack_rate if use_pack else 0
            finish_cost = qty*finish_rate if use_finish else 0
            hpp = material_cost+ink_cost+lam_cost+cut_cost+pack_cost+finish_cost
            auto_price = round(hpp*(1+margin/100))
            st.session_state["calculation"] = {
                "tanggal":str(order_date),"waktu":str(order_time),"jenis_cetak":material_name,"ukuran":size,
                "jumlah":int(qty),"luas_total":float(area),"biaya_bahan":material_cost,"biaya_tinta":ink_cost,
                "biaya_laminasi":lam_cost,"biaya_potong":cut_cost,"biaya_packing":pack_cost,
                "biaya_finishing":finish_cost,"total_hpp":hpp,"margin":margin,"harga_jual":auto_price,
                "estimasi_laba":auto_price-hpp,"keterangan":customer,"pakai_laminasi":int(use_lam),
                "pakai_potong":int(use_cut),"pakai_packing":int(use_pack),"pakai_finishing":int(use_finish),
                "harga_bahan_satuan":material_price,"harga_tinta_satuan":ink_rate,
                "harga_laminasi_satuan":lam_rate,"harga_potong_satuan":cut_rate,
                "harga_packing_satuan":pack_rate,"harga_finishing_satuan":finish_rate}
        if "calculation" in st.session_state:
            result = st.session_state["calculation"]
            st.divider()
            st.subheader("Rincian kalkulasi")
            rows = [
                ("Bahan",result["biaya_bahan"]),("Tinta",result["biaya_tinta"]),
                ("Laminasi",result["biaya_laminasi"]),("Potong",result["biaya_potong"]),
                ("Packing",result["biaya_packing"]),("Finishing",result["biaya_finishing"])]
            st.table(pd.DataFrame(rows,columns=["Komponen","Biaya (Rp)"]))
            st.metric("Total HPP",money(result["total_hpp"]))
            final_price = st.number_input("Harga jual final (dapat diedit)",min_value=0.0,
                                          value=float(result["harga_jual"]),step=1000.0,key="final_price")
            profit = final_price-result["total_hpp"]
            c1,c2 = st.columns(2)
            c1.metric("Harga jual",money(final_price))
            c2.metric("Estimasi laba",money(profit))
            if st.button("💾 Simpan sebagai pesanan",type="primary",use_container_width=True):
                result["harga_jual"] = float(final_price)
                result["estimasi_laba"] = float(profit)
                fields = list(result.keys())
                with conn_db() as con:
                    con.execute(f"INSERT INTO pesanan({','.join(fields)},status) VALUES({','.join(['?']*len(fields))},?)",
                                [result[k] for k in fields]+["Baru"])
                del st.session_state["calculation"]
                if "final_price" in st.session_state: del st.session_state["final_price"]
                st.success("Pesanan berhasil disimpan."); st.rerun()

elif menu == "Daftar Pesanan":
    st.title("📦 Daftar Pesanan")
    if orders.empty:
        st.info("Belum ada pesanan.")
    else:
        status_filter = st.multiselect("Filter status",["Baru","Proses","Selesai","Batal"],default=["Baru","Proses","Selesai"])
        filtered = orders[orders.status.isin(status_filter)]
        show_cols = [c for c in ["id","tanggal","waktu","jenis_cetak","ukuran","jumlah","pakai_laminasi","pakai_potong","pakai_packing","harga_jual","estimasi_laba","status","keterangan"] if c in filtered.columns]
        st.dataframe(filtered[show_cols],use_container_width=True,hide_index=True)
        st.divider()
        st.subheader("Ubah status pesanan")
        c1,c2 = st.columns(2)
        oid = c1.number_input("ID pesanan",min_value=1,step=1)
        new_status = c2.selectbox("Status baru",["Baru","Proses","Selesai","Batal"])
        if st.button("Simpan status"):
            with conn_db() as con: con.execute("UPDATE pesanan SET status=? WHERE id=?",(new_status,int(oid)))
            st.success("Status diperbarui."); st.rerun()
        st.subheader("Nota PDF")
        receipt_id = st.number_input("ID pesanan untuk nota",min_value=1,step=1,key="receipt_id")
        if st.button("Buat nota PDF"):
            row = read_df("SELECT * FROM pesanan WHERE id=?",(int(receipt_id),))
            if row.empty: st.error("ID pesanan tidak ditemukan.")
            else:
                pdf = pdf_receipt(row.iloc[0].to_dict())
                data = pdf.output(dest="S")
                if isinstance(data,str): data=data.encode("latin-1")
                st.download_button("⬇️ Download nota",data=data,file_name=f"Nota_FinPrint_{receipt_id}.pdf",mime="application/pdf")

elif menu == "Laporan":
    st.title("📈 Laporan")
    tab1,tab2 = st.tabs(["Keuangan","Pesanan"])
    with tab1:
        if trans.empty: st.info("Belum ada transaksi.")
        else:
            t=trans.copy()
            t["bulan"]=pd.to_datetime(t.tanggal,errors="coerce").dt.to_period("M").astype(str)
            months=sorted(t.bulan.dropna().unique(),reverse=True)
            month=st.selectbox("Pilih bulan",months)
            m=t[t.bulan==month]
            inc=m[m.jenis=="Pemasukan"].jumlah.sum()
            out=m[m.jenis=="Pengeluaran"].jumlah.sum()
            a,b,c=st.columns(3); a.metric("Pemasukan",money(inc)); b.metric("Pengeluaran",money(out)); c.metric("Selisih",money(inc-out))
            st.dataframe(m.groupby(["jenis","kategori"],as_index=False).jumlah.sum(),use_container_width=True,hide_index=True)
            st.download_button("Ekspor transaksi CSV",m.to_csv(index=False).encode("utf-8-sig"),"laporan_transaksi.csv","text/csv")
    with tab2:
        if orders.empty: st.info("Belum ada pesanan.")
        else:
            a,b,c=st.columns(3)
            a.metric("Total HPP",money(orders.total_hpp.sum()))
            b.metric("Omzet pesanan",money(orders.harga_jual.sum()))
            c.metric("Estimasi laba",money(orders.estimasi_laba.sum()))
            st.dataframe(orders,use_container_width=True,hide_index=True)
            st.download_button("Ekspor pesanan CSV",orders.to_csv(index=False).encode("utf-8-sig"),"laporan_pesanan.csv","text/csv")

elif menu == "Pengaturan" and admin:
    st.title("⚙️ Pengaturan")
    tab1,tab2,tab3 = st.tabs(["Biaya default","Master bahan","Pengguna"])
    with tab1:
        with st.form("settings_form"):
            ink=st.number_input("Tinta per m² (Rp)",min_value=0.0,value=float(settings["tinta_per_m2"]),step=500.0)
            lam=st.number_input("Laminasi per m² (Rp)",min_value=0.0,value=float(settings["laminasi_per_m2"]),step=500.0)
            cut=st.number_input("Potong per pcs (Rp)",min_value=0.0,value=float(settings["potong_per_pcs"]),step=100.0)
            pack=st.number_input("Packing per pcs (Rp)",min_value=0.0,value=float(settings["packing_per_pcs"] or 0),step=100.0)
            finish=st.number_input("Finishing per pcs (Rp)",min_value=0.0,value=float(settings["finishing_per_pcs"]),step=100.0)
            marg=st.number_input("Margin default (%)",min_value=0.0,value=float(settings["margin_default"]),step=5.0)
            if st.form_submit_button("Simpan biaya default",type="primary"):
                with conn_db() as con:
                    con.execute("""UPDATE pengaturan SET tinta_per_m2=?,laminasi_per_m2=?,potong_per_pcs=?,
                    packing_per_pcs=?,finishing_per_pcs=?,margin_default=? WHERE id=1""",(ink,lam,cut,pack,finish,marg))
                st.success("Pengaturan disimpan."); st.rerun()
    with tab2:
        st.dataframe(materials,use_container_width=True,hide_index=True)
        st.markdown("#### Tambah bahan")
        with st.form("add_material",clear_on_submit=True):
            n=st.text_input("Nama bahan")
            unit=st.selectbox("Satuan",["Per Lembar","Per m²","Per Meter","Per Roll"])
            price=st.number_input("Harga satuan (Rp)",min_value=0.0,step=500.0)
            note=st.text_input("Keterangan")
            if st.form_submit_button("Tambah bahan"):
                if n.strip():
                    with conn_db() as con: con.execute("INSERT INTO bahan(nama,satuan,harga,keterangan) VALUES(?,?,?,?)",(n.strip(),unit,price,note))
                    st.success("Bahan ditambahkan."); st.rerun()
        if not materials.empty:
            st.markdown("#### Ubah harga / data bahan")
            mat_id=st.selectbox("Pilih bahan",materials.id.tolist(),format_func=lambda x: materials.loc[materials.id==x,"nama"].iloc[0])
            current=materials[materials.id==mat_id].iloc[0]
            with st.form("edit_material"):
                en=st.text_input("Nama",str(current.nama))
                eu=st.selectbox("Satuan",["Per Lembar","Per m²","Per Meter","Per Roll"],index=["Per Lembar","Per m²","Per Meter","Per Roll"].index(current.satuan))
                ep=st.number_input("Harga (Rp)",min_value=0.0,value=float(current.harga),step=500.0)
                ek=st.text_input("Keterangan",str(current.keterangan or ""))
                if st.form_submit_button("Simpan perubahan"):
                    with conn_db() as con: con.execute("UPDATE bahan SET nama=?,satuan=?,harga=?,keterangan=? WHERE id=?",(en,eu,ep,ek,int(mat_id)))
                    st.success("Data bahan diperbarui."); st.rerun()
            if st.button("Hapus bahan terpilih"):
                with conn_db() as con: con.execute("DELETE FROM bahan WHERE id=?",(int(mat_id),))
                st.rerun()
    with tab3:
        users=read_df("SELECT id,username,role,nama FROM users")
        st.dataframe(users,use_container_width=True,hide_index=True)
        with st.form("new_user",clear_on_submit=True):
            un=st.text_input("Username baru")
            pw=st.text_input("Password",type="password")
            nm=st.text_input("Nama")
            role=st.selectbox("Hak akses",["staff","admin"])
            if st.form_submit_button("Tambah pengguna"):
                try:
                    with conn_db() as con: con.execute("INSERT INTO users(username,password,role,nama) VALUES(?,?,?,?)",(un,hash_password(pw),role,nm))
                    st.success("Pengguna ditambahkan."); st.rerun()
                except sqlite3.IntegrityError: st.error("Username sudah dipakai.")
        st.caption("Catatan: akun admin awal menggunakan password finprint123. Fitur ubah password tersedia pada pembaruan berikutnya; gunakan perangkat lokal yang aman.")

st.sidebar.caption("FinPrint Pro • Database bersama PC + Android")
