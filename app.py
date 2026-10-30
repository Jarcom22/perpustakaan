"""Sistem Informasi Perpustakaan (Flask + SQLite).
Jalankan: pip install flask  ->  python app.py  ->  buka http://127.0.0.1:5000
Akun demo: admin/admin123, pustakawan/pustaka123, anggota/anggota123
"""
import os
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from jinja2 import DictLoader
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = "ganti-kunci-ini-sebelum-dikumpulkan"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perpus.db")
STAF = ("pustakawan", "admin")
LABEL = {"tarif_denda": "Tarif denda per hari (Rp)", "lama_pinjam": "Lama pinjam (hari)",
         "maks_pinjam": "Maksimal buku dipinjam", "maks_perpanjang": "Maksimal perpanjangan",
         "denda_hilang": "Denda buku hilang atau rusak (Rp)"}

SCHEMA = """
create table if not exists users(id integer primary key, nama text, username text unique, email text unique,
  sandi text, peran text, aktif integer default 1);
create table if not exists buku(id integer primary key, judul text, penulis text, kategori text, tahun integer);
create table if not exists eksemplar(id integer primary key, buku_id integer, kode text unique, status text default 'tersedia');
create table if not exists pinjam(id integer primary key, user_id integer, eksemplar_id integer, tgl_pinjam text,
  jatuh_tempo text, tgl_kembali text, perpanjang integer default 0, status text default 'dipinjam');
create table if not exists denda(id integer primary key, pinjam_id integer, hari integer, jumlah integer, kondisi text);
create table if not exists aturan(kunci text primary key, nilai text);
"""


def init_db():
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    if not c.execute("select 1 from users").fetchone():
        for n, u, e, p, r in [("Administrator", "admin", "admin@kampus.ac.id", "admin123", "admin"),
                              ("Petugas Pustaka", "pustakawan", "pustaka@kampus.ac.id", "pustaka123", "pustakawan"),
                              ("Anggota Contoh", "anggota", "anggota@kampus.ac.id", "anggota123", "anggota")]:
            c.execute("insert into users(nama,username,email,sandi,peran) values(?,?,?,?,?)",
                      (n, u, e, generate_password_hash(p), r))
        for k, v in [("tarif_denda", 1000), ("lama_pinjam", 7), ("maks_pinjam", 3), ("maks_perpanjang", 1), ("denda_hilang", 50000)]:
            c.execute("insert into aturan values(?,?)", (k, str(v)))
        for j, p, k, t in [("Dasar-Dasar Pemrograman Python", "Budi Raharjo", "Pemrograman", 2021),
                           ("Basis Data Relasional", "Fathansyah", "Basis Data", 2018),
                           ("Jaringan Komputer", "Andrew Tanenbaum", "Jaringan", 2015),
                           ("Rekayasa Perangkat Lunak", "Rosa A. S.", "Rekayasa", 2019),
                           ("Keamanan Informasi", "Mark Stamp", "Keamanan", 2020)]:
            i = c.execute("insert into buku(judul,penulis,kategori,tahun) values(?,?,?,?)", (j, p, k, t)).lastrowid
            for n in (1, 2):
                c.execute("insert into eksemplar(buku_id,kode) values(?,?)", (i, f"B{i:03d}-{n}"))
    c.commit()
    c.close()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def tutup(_):
    d = g.pop("db", None)
    if d:
        d.close()


def q(sql, a=(), one=False):
    r = db().execute(sql, a).fetchall()
    return (r[0] if r else None) if one else r


def run(sql, a=()):
    c = db().execute(sql, a)
    db().commit()
    return c


def aturan(k):
    return int(q("select nilai from aturan where kunci=?", (k,), one=True)["nilai"])


def hari():
    return date.today().isoformat()


@app.before_request
def muat_user():
    g.user = q("select * from users where id=? and aktif=1", (session["uid"],), one=True) if "uid" in session else None


@app.context_processor
def konteks():
    return dict(user=g.user)


def butuh(*peran):
    def deko(f):
        @wraps(f)
        def w(*a, **k):
            if not g.user:
                flash("Silakan masuk dulu.", "err")
                return redirect(url_for("login"))
            if g.user["peran"] not in peran:
                abort(403)
            return f(*a, **k)
        return w
    return deko


BUKU_SQL = """select b.*, (select count(*) from eksemplar e where e.buku_id=b.id and e.status='tersedia') tersedia,
 (select count(*) from eksemplar e where e.buku_id=b.id) total from buku b
 where judul like ? or penulis like ? or kategori like ? order by judul"""
PINJAM_SQL = """select p.*, u.nama, b.judul, e.kode from pinjam p join users u on u.id=p.user_id
 join eksemplar e on e.id=p.eksemplar_id join buku b on b.id=e.buku_id """


# ---------- Publik ----------
@app.route("/")
def katalog():
    kw = request.args.get("q", "").strip()
    return render_template("katalog.html", rows=q(BUKU_SQL, (f"%{kw}%",) * 3), kw=kw)


@app.route("/daftar", methods=["GET", "POST"])
def daftar():
    if request.method == "POST":
        nama, u, e, p = (request.form.get(x, "").strip() for x in ("nama", "username", "email", "sandi"))
        if not all((nama, u, e, p)) or len(p) < 6:
            flash("Semua kolom wajib diisi dan kata sandi minimal 6 karakter.", "err")
        elif q("select 1 from users where username=? or email=?", (u, e), one=True):
            flash("Username atau email sudah dipakai.", "err")
        else:
            run("insert into users(nama,username,email,sandi,peran) values(?,?,?,?,'anggota')",
                (nama, u, e, generate_password_hash(p)))
            flash("Akun berhasil dibuat. Silakan masuk.", "ok")
            return redirect(url_for("login"))
    return render_template("daftar.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        i = request.form.get("id", "").strip()
        u = q("select * from users where username=? or email=?", (i, i), one=True)
        if u and u["aktif"] and check_password_hash(u["sandi"], request.form.get("sandi", "")):
            session.clear()
            session["uid"] = u["id"]
            return redirect(url_for("dasbor"))
        flash("Username, email, atau kata sandi salah, atau akun nonaktif.", "err")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("katalog"))


# ---------- Anggota ----------
@app.route("/riwayat")
@butuh("anggota")
def riwayat():
    rows = q(PINJAM_SQL + "where p.user_id=? order by p.id desc", (g.user["id"],))
    return render_template("riwayat.html", rows=rows, hari=hari())


# ---------- Pustakawan dan admin ----------
@app.route("/dasbor")
@butuh("anggota", "pustakawan", "admin")
def dasbor():
    if g.user["peran"] == "anggota":
        return redirect(url_for("riwayat"))
    n = lambda s, a=(): q(s, a, one=True)[0]
    st = dict(buku=n("select count(*) from buku"), tersedia=n("select count(*) from eksemplar where status='tersedia'"),
              dipinjam=n("select count(*) from pinjam where status='dipinjam'"),
              telat=n("select count(*) from pinjam where status='dipinjam' and jatuh_tempo<?", (hari(),)),
              denda=n("select coalesce(sum(jumlah),0) from denda"))
    populer = q("""select b.judul, count(*) n from pinjam p join eksemplar e on e.id=p.eksemplar_id
                   join buku b on b.id=e.buku_id group by b.id order by n desc limit 5""")
    return render_template("dasbor.html", st=st, populer=populer, rows=q(PINJAM_SQL + "order by p.id desc limit 10"))


@app.route("/buku", methods=["GET", "POST"])
@butuh(*STAF)
def buku():
    if request.method == "POST":
        f = request.form
        if not f.get("judul", "").strip():
            flash("Judul buku wajib diisi.", "err")
        else:
            i = run("insert into buku(judul,penulis,kategori,tahun) values(?,?,?,?)",
                    (f["judul"].strip(), f.get("penulis"), f.get("kategori"), f.get("tahun") or None)).lastrowid
            for k in range(max(1, min(int(f.get("jumlah") or 1), 20))):
                run("insert into eksemplar(buku_id,kode) values(?,?)", (i, f"B{i:03d}-{k + 1}"))
            flash("Buku ditambahkan.", "ok")
        return redirect(url_for("buku"))
    return render_template("buku.html", rows=q(BUKU_SQL, ("%%",) * 3), aksi=True)


@app.post("/buku/<int:i>/hapus")
@butuh(*STAF)
def hapus_buku(i):
    if q("""select 1 from pinjam p join eksemplar e on e.id=p.eksemplar_id where e.buku_id=?""", (i,), one=True):
        flash("Buku punya riwayat peminjaman, jadi tidak bisa dihapus.", "err")
    else:
        run("delete from eksemplar where buku_id=?", (i,))
        run("delete from buku where id=?", (i,))
        flash("Buku dihapus.", "ok")
    return redirect(url_for("buku"))


@app.route("/anggota")
@butuh(*STAF)
def anggota():
    return render_template("pengguna.html", rows=q("select * from users where peran='anggota' order by nama"), judul="Data anggota")


@app.route("/pengguna", methods=["GET", "POST"])
@butuh("admin")
def pengguna():
    if request.method == "POST":
        nama, u, e, p = (request.form.get(x, "").strip() for x in ("nama", "username", "email", "sandi"))
        r = request.form.get("peran")
        if not all((nama, u, e, p)) or len(p) < 6 or r not in STAF:
            flash("Lengkapi semua kolom, kata sandi minimal 6 karakter.", "err")
        elif q("select 1 from users where username=? or email=?", (u, e), one=True):
            flash("Username atau email sudah dipakai.", "err")
        else:
            run("insert into users(nama,username,email,sandi,peran) values(?,?,?,?,?)", (nama, u, e, generate_password_hash(p), r))
            flash("Pengguna ditambahkan.", "ok")
        return redirect(url_for("pengguna"))
    return render_template("pengguna.html", rows=q("select * from users order by peran, nama"), judul="Kelola pengguna", form=True)


@app.post("/pengguna/<int:i>/toggle")
@butuh(*STAF)
def toggle(i):
    u = q("select * from users where id=?", (i,), one=True)
    if u and u["id"] != g.user["id"] and (u["peran"] == "anggota" or g.user["peran"] == "admin"):
        run("update users set aktif=1-aktif where id=?", (i,))
    return redirect(request.referrer or url_for("anggota"))


@app.route("/pinjam", methods=["GET", "POST"])
@butuh(*STAF)
def pinjam():
    if request.method == "POST":
        a = q("select * from users where id=? and peran='anggota'", (request.form.get("anggota"),), one=True)
        e = q("select * from eksemplar where id=?", (request.form.get("eksemplar"),), one=True)
        n = q("select count(*) from pinjam where user_id=? and status='dipinjam'", (a["id"] if a else 0,), one=True)[0]
        if not a or not a["aktif"]:
            alasan = "Anggota tidak ditemukan atau nonaktif."
        elif n >= aturan("maks_pinjam"):
            alasan = f"Anggota sudah meminjam {n} buku, batas maksimal tercapai."
        elif q("select 1 from pinjam where user_id=? and status='dipinjam' and jatuh_tempo<?", (a["id"], hari()), one=True):
            alasan = "Anggota masih punya buku yang lewat jatuh tempo."
        elif not e or e["status"] != "tersedia":
            alasan = "Eksemplar tidak tersedia."
        else:
            jt = (date.today() + timedelta(days=aturan("lama_pinjam"))).isoformat()
            run("insert into pinjam(user_id,eksemplar_id,tgl_pinjam,jatuh_tempo) values(?,?,?,?)", (a["id"], e["id"], hari(), jt))
            run("update eksemplar set status='dipinjam' where id=?", (e["id"],))
            flash(f"Peminjaman tersimpan. Jatuh tempo {jt}.", "ok")
            return redirect(url_for("transaksi"))
        flash(alasan, "err")
    return render_template("pinjam.html", ang=q("select id,nama,username from users where peran='anggota' and aktif=1 order by nama"),
                           eks=q("select e.id,e.kode,b.judul from eksemplar e join buku b on b.id=e.buku_id where e.status='tersedia' order by b.judul"))


@app.route("/transaksi")
@butuh(*STAF)
def transaksi():
    return render_template("transaksi.html", rows=q(PINJAM_SQL + "where p.status='dipinjam' order by p.jatuh_tempo"), hari=hari())


@app.post("/perpanjang/<int:i>")
@butuh(*STAF)
def perpanjang(i):
    p = q("select * from pinjam where id=? and status='dipinjam'", (i,), one=True) or abort(404)
    if p["jatuh_tempo"] < hari():
        flash("Tidak bisa diperpanjang karena sudah lewat jatuh tempo.", "err")
    elif p["perpanjang"] >= aturan("maks_perpanjang"):
        flash("Batas perpanjangan sudah tercapai.", "err")
    else:
        jt = (date.fromisoformat(p["jatuh_tempo"]) + timedelta(days=aturan("lama_pinjam"))).isoformat()
        run("update pinjam set jatuh_tempo=?, perpanjang=perpanjang+1 where id=?", (jt, i))
        flash(f"Diperpanjang sampai {jt}.", "ok")
    return redirect(url_for("transaksi"))


@app.route("/kembali/<int:i>", methods=["GET", "POST"])
@butuh(*STAF)
def kembali(i):
    p = q(PINJAM_SQL + "where p.id=? and p.status='dipinjam'", (i,), one=True) or abort(404)
    telat = max(0, (date.today() - date.fromisoformat(p["jatuh_tempo"])).days)
    denda = telat * aturan("tarif_denda")
    if request.method == "POST":
        kondisi = request.form.get("kondisi", "baik")
        if kondisi not in ("baik", "rusak", "hilang"):
            abort(400)
        if kondisi != "baik":
            denda += aturan("denda_hilang")
        if denda and not request.form.get("bayar"):
            flash("Konfirmasi pembayaran denda dulu.", "err")
        else:
            run("update pinjam set status='kembali', tgl_kembali=? where id=?", (hari(), i))
            run("update eksemplar set status=? where id=?", ("tersedia" if kondisi == "baik" else kondisi, p["eksemplar_id"]))
            if denda:
                run("insert into denda(pinjam_id,hari,jumlah,kondisi) values(?,?,?,?)", (i, telat, denda, kondisi))
            flash(f"Pengembalian selesai. Denda Rp {denda:,}.".replace(",", "."), "ok")
            return redirect(url_for("transaksi"))
    return render_template("kembali.html", p=p, telat=telat, denda=denda, tarif=aturan("tarif_denda"), flat=aturan("denda_hilang"))


@app.route("/aturan", methods=["GET", "POST"])
@butuh("admin")
def atur():
    if request.method == "POST":
        for k in LABEL:
            v = request.form.get(k, "").strip()
            if v.isdigit():
                run("update aturan set nilai=? where kunci=?", (v, k))
        flash("Aturan disimpan.", "ok")
        return redirect(url_for("atur"))
    return render_template("aturan.html", rows=q("select * from aturan"), label=LABEL)


# ---------- Tampilan ----------
CSS = """:root{--bg:#edf1f4;--tinta:#16213a;--aksen:#0e6b63;--bahaya:#a33a2b;--garis:#c9d3dc;--putih:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tinta);font:16px/1.55 "Segoe UI",system-ui,sans-serif}
header{background:var(--tinta);display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;align-items:center;padding:.8rem 1.2rem}
.brand{font:700 1.25rem Georgia,serif;color:#fff;text-decoration:none}nav{display:flex;flex-wrap:wrap;gap:.2rem 1rem}
nav a{color:#c9d6e8;text-decoration:none;padding:.2rem 0}nav a:hover,nav a:focus-visible{color:#fff;text-decoration:underline}
main{max-width:1000px;margin:0 auto;padding:1.5rem 1.2rem 3rem}h1{font:700 1.8rem Georgia,serif;margin:.2rem 0 1rem}
.card{background:var(--putih);border:1px solid var(--garis);border-radius:6px;padding:1.2rem;margin-bottom:1.2rem;max-width:520px}
.scroll{overflow-x:auto;background:var(--putih);border:1px solid var(--garis);border-radius:6px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.55rem .8rem;border-bottom:1px solid var(--garis);vertical-align:middle}
th{background:#e3e9ee;font-weight:600}label{display:block;margin:.7rem 0 .2rem;font-weight:600}
input,select{width:100%;padding:.55rem;border:1px solid #8a9aab;border-radius:4px;font:inherit;background:#fff}
button,.btn{background:var(--aksen);color:#fff;border:0;border-radius:4px;padding:.55rem 1rem;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #f2b705;outline-offset:2px}
.lnk{background:none;color:var(--bahaya);padding:0;text-decoration:underline}.cari{display:flex;gap:.5rem;margin-bottom:1rem}.cari input{flex:1}
.msg{padding:.7rem 1rem;border-radius:4px;border-left:5px solid}.ok{background:#dcf1ec;border-color:var(--aksen)}.err{background:#f8e0dc;border-color:var(--bahaya)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem;margin-bottom:1.4rem}
.stat{background:var(--putih);border:1px solid var(--garis);border-left:5px solid var(--aksen);border-radius:6px;padding:.8rem}
.stat b{display:block;font:700 1.7rem Georgia,serif}.telat{color:var(--bahaya);font-weight:600}form.in{display:inline}
@media(max-width:600px){.cari{flex-direction:column}}"""

T = {}
T["base.html"] = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Perpustakaan Kampus</title><style>""" + CSS + """</style></head><body>
<header><a class="brand" href="/">Perpustakaan Kampus</a><nav><a href="/">Katalog</a>
{% if user %}{% if user.peran=='anggota' %}<a href="/riwayat">Riwayat saya</a>{% else %}<a href="/dasbor">Dasbor</a><a href="/buku">Buku</a><a href="/anggota">Anggota</a><a href="/pinjam">Pinjam</a><a href="/transaksi">Transaksi</a>{% endif %}
{% if user.peran=='admin' %}<a href="/aturan">Aturan</a><a href="/pengguna">Pengguna</a>{% endif %}<a href="/logout">Keluar ({{ user.username }})</a>
{% else %}<a href="/daftar">Daftar</a><a href="/login">Masuk</a>{% endif %}</nav></header>
<main>{% for c,m in get_flashed_messages(with_categories=true) %}<p class="msg {{ c }}" role="alert">{{ m }}</p>{% endfor %}
{% block content %}{% endblock %}</main></body></html>"""

T["tabel_buku.html"] = """<div class="scroll"><table><tr><th>Judul</th><th>Penulis</th><th>Kategori</th><th>Tahun</th><th>Tersedia</th>{% if aksi %}<th></th>{% endif %}</tr>
{% for b in rows %}<tr><td>{{ b.judul }}</td><td>{{ b.penulis or '' }}</td><td>{{ b.kategori or '' }}</td><td>{{ b.tahun or '' }}</td><td>{{ b.tersedia }} dari {{ b.total }}</td>
{% if aksi %}<td><form method="post" action="/buku/{{ b.id }}/hapus"><button class="lnk">Hapus</button></form></td>{% endif %}</tr>
{% else %}<tr><td colspan="6">Buku tidak ditemukan. Coba kata kunci lain.</td></tr>{% endfor %}</table></div>"""

T["katalog.html"] = """{% extends "base.html" %}{% block content %}<h1>Katalog buku</h1>
<form class="cari" method="get"><input name="q" value="{{ kw }}" placeholder="Judul, penulis, atau kategori" aria-label="Cari buku"><button>Cari buku</button></form>
{% include "tabel_buku.html" %}{% endblock %}"""

T["daftar.html"] = """{% extends "base.html" %}{% block content %}<h1>Buat akun anggota</h1><form class="card" method="post">
<label for="n">Nama lengkap</label><input id="n" name="nama" required><label for="u">Username</label><input id="u" name="username" required>
<label for="e">Email</label><input id="e" name="email" type="email" required><label for="s">Kata sandi (minimal 6 karakter)</label><input id="s" name="sandi" type="password" required>
<p><button>Buat akun</button></p></form>{% endblock %}"""

T["login.html"] = """{% extends "base.html" %}{% block content %}<h1>Masuk</h1><form class="card" method="post">
<label for="i">Username atau email</label><input id="i" name="id" required autofocus><label for="s">Kata sandi</label><input id="s" name="sandi" type="password" required>
<p><button>Masuk</button></p><p>Akun demo: admin / admin123, pustakawan / pustaka123, anggota / anggota123</p></form>{% endblock %}"""

T["riwayat.html"] = """{% extends "base.html" %}{% block content %}<h1>Riwayat pinjaman saya</h1><div class="scroll"><table>
<tr><th>Buku</th><th>Kode</th><th>Dipinjam</th><th>Jatuh tempo</th><th>Dikembalikan</th><th>Status</th></tr>
{% for p in rows %}<tr><td>{{ p.judul }}</td><td>{{ p.kode }}</td><td>{{ p.tgl_pinjam }}</td><td>{{ p.jatuh_tempo }}</td><td>{{ p.tgl_kembali or '' }}</td>
<td>{% if p.status=='dipinjam' and p.jatuh_tempo<hari %}<span class="telat">Terlambat</span>{% else %}{{ p.status|capitalize }}{% endif %}</td></tr>
{% else %}<tr><td colspan="6">Belum ada pinjaman. Cari buku di katalog lalu datangi pustakawan.</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["dasbor.html"] = """{% extends "base.html" %}{% block content %}<h1>Dasbor</h1><div class="grid">
<div class="stat"><b>{{ st.buku }}</b>Judul buku</div><div class="stat"><b>{{ st.tersedia }}</b>Eksemplar tersedia</div>
<div class="stat"><b>{{ st.dipinjam }}</b>Sedang dipinjam</div><div class="stat"><b>{{ st.telat }}</b>Terlambat</div>
<div class="stat"><b>Rp {{ '{:,}'.format(st.denda).replace(',', '.') }}</b>Total denda</div></div>
<h2>Buku paling sering dipinjam</h2><div class="scroll"><table>{% for b in populer %}<tr><td>{{ b.judul }}</td><td>{{ b.n }}x</td></tr>
{% else %}<tr><td>Belum ada data peminjaman.</td></tr>{% endfor %}</table></div>
<h2>Transaksi terbaru</h2><div class="scroll"><table><tr><th>Anggota</th><th>Buku</th><th>Pinjam</th><th>Status</th></tr>
{% for p in rows %}<tr><td>{{ p.nama }}</td><td>{{ p.judul }}</td><td>{{ p.tgl_pinjam }}</td><td>{{ p.status|capitalize }}</td></tr>
{% else %}<tr><td colspan="4">Belum ada transaksi.</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["buku.html"] = """{% extends "base.html" %}{% block content %}<h1>Kelola data buku</h1><form class="card" method="post">
<label for="j">Judul</label><input id="j" name="judul" required><label for="p">Penulis</label><input id="p" name="penulis">
<label for="k">Kategori</label><input id="k" name="kategori"><label for="t">Tahun terbit</label><input id="t" name="tahun" type="number">
<label for="m">Jumlah eksemplar</label><input id="m" name="jumlah" type="number" value="1" min="1" max="20"><p><button>Simpan buku</button></p></form>
{% include "tabel_buku.html" %}{% endblock %}"""

T["pengguna.html"] = """{% extends "base.html" %}{% block content %}<h1>{{ judul }}</h1>
{% if form %}<form class="card" method="post"><label for="n">Nama</label><input id="n" name="nama" required><label for="u">Username</label><input id="u" name="username" required>
<label for="e">Email</label><input id="e" name="email" type="email" required><label for="s">Kata sandi</label><input id="s" name="sandi" type="password" required>
<label for="r">Peran</label><select id="r" name="peran"><option>pustakawan</option><option>admin</option></select><p><button>Tambah pengguna</button></p></form>{% endif %}
<div class="scroll"><table><tr><th>Nama</th><th>Username</th><th>Email</th><th>Peran</th><th>Status</th><th></th></tr>
{% for u in rows %}<tr><td>{{ u.nama }}</td><td>{{ u.username }}</td><td>{{ u.email }}</td><td>{{ u.peran }}</td><td>{{ 'Aktif' if u.aktif else 'Nonaktif' }}</td>
<td>{% if u.id!=user.id %}<form method="post" action="/pengguna/{{ u.id }}/toggle"><button class="lnk">{{ 'Nonaktifkan' if u.aktif else 'Aktifkan' }}</button></form>{% endif %}</td></tr>
{% else %}<tr><td colspan="6">Belum ada data.</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["pinjam.html"] = """{% extends "base.html" %}{% block content %}<h1>Proses peminjaman</h1><form class="card" method="post">
<label for="a">Anggota</label><select id="a" name="anggota" required>{% for a in ang %}<option value="{{ a.id }}">{{ a.nama }} ({{ a.username }})</option>{% endfor %}</select>
<label for="e">Eksemplar buku</label><select id="e" name="eksemplar" required>{% for e in eks %}<option value="{{ e.id }}">{{ e.judul }} - {{ e.kode }}</option>{% endfor %}</select>
<p><button>Simpan peminjaman</button></p></form>{% endblock %}"""

T["transaksi.html"] = """{% extends "base.html" %}{% block content %}<h1>Peminjaman aktif</h1><div class="scroll"><table>
<tr><th>Anggota</th><th>Buku</th><th>Kode</th><th>Jatuh tempo</th><th></th></tr>
{% for p in rows %}<tr><td>{{ p.nama }}</td><td>{{ p.judul }}</td><td>{{ p.kode }}</td>
<td>{{ p.jatuh_tempo }}{% if p.jatuh_tempo<hari %} <span class="telat">(terlambat)</span>{% endif %}</td>
<td><form class="in" method="post" action="/perpanjang/{{ p.id }}"><button class="lnk" style="color:var(--aksen)">Perpanjang</button></form>
<a class="btn" href="/kembali/{{ p.id }}">Kembalikan</a></td></tr>
{% else %}<tr><td colspan="5">Tidak ada pinjaman aktif.</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["kembali.html"] = """{% extends "base.html" %}{% block content %}<h1>Pengembalian buku</h1><form class="card" method="post">
<p><b>{{ p.judul }}</b> ({{ p.kode }})<br>Dipinjam oleh {{ p.nama }}, jatuh tempo {{ p.jatuh_tempo }}.</p>
<p>Terlambat {{ telat }} hari x Rp {{ tarif }} = <b>Rp {{ telat*tarif }}</b></p>
<label for="k">Kondisi buku</label><select id="k" name="kondisi"><option value="baik">Baik</option><option value="rusak">Rusak</option><option value="hilang">Hilang</option></select>
<p>Buku rusak atau hilang dikenai tambahan Rp {{ flat }}.</p>
<label><input type="checkbox" name="bayar" value="1" style="width:auto"> Denda sudah dibayar atau tidak ada denda</label>
<p><button>Konfirmasi pengembalian</button></p></form>{% endblock %}"""

T["aturan.html"] = """{% extends "base.html" %}{% block content %}<h1>Aturan perpustakaan</h1><form class="card" method="post">
{% for r in rows %}<label for="{{ r.kunci }}">{{ label[r.kunci] }}</label><input id="{{ r.kunci }}" name="{{ r.kunci }}" type="number" min="0" value="{{ r.nilai }}">{% endfor %}
<p><button>Simpan aturan</button></p></form>{% endblock %}"""

app.jinja_env.loader = DictLoader(T)

if __name__ == "__main__":
    init_db()
    # host 0.0.0.0 agar bisa dibuka dari HP di WiFi yang sama; debug dimatikan demi keamanan
    app.run(host="0.0.0.0", port=5000, debug=False)
