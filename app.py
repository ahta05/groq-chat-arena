import csv
import io
import json
import os
import re
import time
from datetime import datetime

import streamlit as st
from openai import OpenAI, APIConnectionError

# ================== PENGATURAN HALAMAN ==================
st.set_page_config(page_title="Room Chat AI - Eksperimen", page_icon="🔬", layout="wide")

# ================== PENYEDIA (SEMUA KOMPATIBEL FORMAT OPENAI) ==================
BASE_URL = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}
NAMA_KUNCI = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# ================== PARTISIPAN (NAMA ASLI MODEL) ==================
# "penyedia" = siapa yang melayani; "id" = nama resmi model di penyedia itu.
# Rujukan ID: console.groq.com/docs/models · aistudio.google.com ·
#             openrouter.ai/models (cari yang berlabel :free)
DAFTAR_MODEL = {
    "GPT-OSS 120B": {"penyedia": "groq", "id": "openai/gpt-oss-120b"},
    "GPT-OSS 20B": {"penyedia": "groq", "id": "openai/gpt-oss-20b"},
    "Qwen 3.8 27B": {"penyedia": "groq", "id": "qwen/qwen3.8-27b"},
    "Gemini 3.8 Flash": {"penyedia": "gemini", "id": "gemini-3.8-flash"},
    "Gemini 3.5 Flash-Lite": {"penyedia": "gemini", "id": "gemini-3.5-flash-lite"},
    "Gemma 4 31B · gratis": {"penyedia": "openrouter", "id": "google/gemma-4-31b-it:free"},
    "Gemma 4 26B · gratis": {"penyedia": "openrouter", "id": "google/gemma-4-26b-a4b-it:free"},
}
DEFAULT_PARTISIPAN = ["GPT-OSS 120B", "GPT-OSS 20B", "Qwen 3.8 27B", "Gemini 3.8 Flash"]
TAG = ["🟦", "🟨", "🟥", "🟩", "🟪", "🟧", "🟫"]  # penanda visual, bukan identitas
TAMPILKAN_ERROR_LENGKAP = True  # True = detail teknis error ikut terlihat peserta

# ================== ATURAN LAB (TIDAK DIUBAH) ==================
MAKS_TOKEN_PER_PESAN = 800   # batas panjang 1 pesan - patuh kuota gratis
BATAS_KARAKTER_LOG = 20000    # memori konteks: 5000 karakter terakhir
JEDA_COBA_LAG = [10, 20]     # kalau kuota sesak: tunggu 10 dtk, lalu 20 dtk

# ================== PENGATURAN TAMBAHAN ==================
BATAS_GAGAL_BERUNTUN = 3     # pemutus otomatis (0 = nonaktif)
DIR_AUTOSAVE = "autosave_sesi"

# Parameter khusus model (dikirim via extra_body), hanya bila "Batasi reasoning" dicentang.
PARAM_EKSTRA = {
    "openai/gpt-oss-120b": {"reasoning_effort": "low"},
    "openai/gpt-oss-20b": {"reasoning_effort": "low"},
}

# ================== KUNCI API (YANG ADA AKTIF, YANG TIDAK DILEWATI) ==================
def ambil_kunci(nama):
    try:
        nilai = str(st.secrets[nama]).strip()
        return nilai or None
    except Exception:
        return None

KUNCI = {p: ambil_kunci(n) for p, n in NAMA_KUNCI.items()}
PENYEDIA_AKTIF = [p for p, k in KUNCI.items() if k]
if not PENYEDIA_AKTIF:
    st.error("🔑 Belum ada satu pun kunci API di Secrets! Buka Manage app → Settings → Secrets.")
    st.stop()

# ================== KLIEN (SATU PUSTAKA UNTUK SEMUA PENYEDIA) ==================
def buat_klien(penyedia):
    tambahan = {}
    if penyedia == "openrouter":
        tambahan["default_headers"] = {"X-Title": "Room Chat AI - Eksperimen"}
    return OpenAI(
        api_key=KUNCI[penyedia],
        base_url=BASE_URL[penyedia],
        timeout=60,
        max_retries=0,  # satu-satunya mekanisme coba-ulang: JEDA_COBA_LAG
        **tambahan,
    )

KLIEN = {p: buat_klien(p) for p in PENYEDIA_AKTIF}

# ================== MESIN STATE ==================
def reset_state():
    st.session_state.transkrip = []
    st.session_state.sedang_jalan = False
    st.session_state.giliran = 0
    st.session_state.gagal_beruntun = 0
    st.session_state.konfigurasi_log = []
    st.session_state.autosave_error = ""
    st.session_state.sesi_id = datetime.now().strftime("%Y%m%d_%H%M%S")

if "transkrip" not in st.session_state:
    reset_state()

# ================== VALIDASI ID MODEL (PER PENYEDIA) ==================
@st.cache_data(ttl=3600, show_spinner=False)
def _ambil_id_model(penyedia):
    # Google sering menambahkan awalan "models/" pada daftar ID - kita lepas dulu
    return sorted(str(m.id).removeprefix("models/") for m in KLIEN[penyedia].models.list().data)

def model_tersedia(penyedia):
    if penyedia not in KLIEN:
        return None
    try:
        return set(_ambil_id_model(penyedia))
    except Exception:
        return None

# ================== UTILITAS ==================
def sekarang():
    return datetime.now().isoformat(timespec="seconds")

def simpan_autosave(rec):
    """Tambahkan satu baris JSON ke file sesi. Gagal menyimpan tidak menghentikan sesi."""
    try:
        os.makedirs(DIR_AUTOSAVE, exist_ok=True)
        path = os.path.join(DIR_AUTOSAVE, f"{st.session_state.sesi_id}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        st.session_state.autosave_error = str(e)

def tambah_entri(rec):
    st.session_state.transkrip.append(rec)
    simpan_autosave(rec)

def daftar_autosave():
    if not os.path.isdir(DIR_AUTOSAVE):
        return []
    return sorted([f for f in os.listdir(DIR_AUTOSAVE) if f.endswith(".jsonl")], reverse=True)

def muat_sesi(nama_file):
    transkrip, konfigurasi = [], []
    with open(os.path.join(DIR_AUTOSAVE, nama_file), encoding="utf-8") as f:
        for baris in f:
            baris = baris.strip()
            if not baris:
                continue
            try:
                rec = json.loads(baris)
            except json.JSONDecodeError:
                continue
            (konfigurasi if rec.get("jenis") == "konfigurasi" else transkrip).append(rec)
    giliran_terpakai = [r.get("giliran", 0) for r in transkrip
                        if r.get("nama") != "SISTEM" and r.get("jenis") != "pengamat"]
    st.session_state.transkrip = transkrip
    st.session_state.konfigurasi_log = konfigurasi
    st.session_state.giliran = (max(giliran_terpakai) + 1) if giliran_terpakai else 0
    st.session_state.sesi_id = nama_file[: -len(".jsonl")]
    st.session_state.sedang_jalan = False
    st.session_state.gagal_beruntun = 0

# ================== KONFIGURASI SESI (TIDAK MASUK KONTEKS MODEL) ==================
def snapshot_konfigurasi(terpilih, topik, jumlah_maks, batasi_reasoning):
    return {
        "peserta": list(terpilih),
        "id_model": {n: DAFTAR_MODEL[n] for n in terpilih},
        "topik": topik.strip(),
        "jumlah_maks": jumlah_maks,
        "reasoning_dibatasi": batasi_reasoning,
        "penyedia_aktif": list(PENYEDIA_AKTIF),
        "aturan": {
            "maks_token_per_pesan": MAKS_TOKEN_PER_PESAN,
            "batas_karakter_log": BATAS_KARAKTER_LOG,
            "jeda_coba_lagi": JEDA_COBA_LAG,
            "batas_gagal_beruntun": BATAS_GAGAL_BERUNTUN,
        },
    }

def catat_konfigurasi_bila_berubah(snap):
    log = st.session_state.konfigurasi_log
    if log:
        terakhir = {k: v for k, v in log[-1].items() if k not in ("jenis", "waktu", "giliran")}
        if terakhir == snap:
            return
    rec = {"jenis": "konfigurasi", "waktu": sekarang(), "giliran": st.session_state.giliran, **snap}
    log.append(rec)
    simpan_autosave(rec)

# ================== MEMORI KONTEKS (CATATAN SISTEM IKUT TERLIHAT) ==================
def bangun_log(transkrip):
    baris_terpilih = []
    total = 0
    for p in reversed(transkrip):
        if p.get("jenis", "pesan") == "catatan":
            baris = f"[SISTEM] {p['teks']}"
        else:
            baris = f"{p['nama']}: {p['teks']}"
        if baris_terpilih and total + len(baris) > BATAS_KARAKTER_LOG:
            break
        baris_terpilih.insert(0, baris)
        total += len(baris)
    return "\n\n".join(baris_terpilih) or "(percakapan belum dimulai - Anda peserta pertama yang bicara)"

# ================== PENGUMUMAN SITUASI ==================
def bangun_pengumuman(daftar_partisipan, nama_model, topik, log):
    semua_nama = ", ".join(daftar_partisipan)
    if topik.strip():
        baris_topik = f"Topik diskusi: {topik.strip()}"
    else:
        baris_topik = "Tidak ada topik yang ditetapkan. Perlakukan ini sebagai percakapan terbuka."
    return (
        f"Anda adalah {nama_model}, sebuah model AI. Anda berpartisipasi dalam percakapan grup "
        f"bersama model AI lainnya: {semua_nama}. {baris_topik}\n\n"
        f"Percakapan sejauh ini:\n\n{log}\n\n"
        f"Sekarang giliran Anda. Tulis SATU pesan berikutnya sebagai {nama_model}, "
        f"dengan kemampuan terbaik dan gaya komunikasi Anda sendiri.\n"
        f"Format ruangan: satu pesan mengalir kira-kira maksimal 150 kata "
        f"(ini ruang chat, bukan dokumen - tanpa judul/tabel/daftar panjang).\n"
        f"Baris berawalan [SISTEM] adalah catatan teknis ruangan, bukan pesan peserta.\n"
        f"Jangan menulis nama Anda di awal pesan, dan jangan menulis pesan atas nama model lain."
    )

# ================== PENGHAPUS TEKS ==================
def bersihkan_teks(teks, nama_model, semua_nama):
    """Buang blok <think>, awalan nama sendiri, dan baris yang mengatasnamakan model lain.
    Versi mentah tetap diarsipkan di metadata."""
    awal = teks.strip()
    teks = re.sub(r"<think>.*?</think>", "", teks, flags=re.S | re.I)
    teks = re.sub(r"<think>.*$", "", teks, flags=re.S | re.I)
    teks = teks.strip()

    pola_sendiri = rf"^[*_\[\s]*{re.escape(nama_model)}[*_\]\s]*:[*_\s]*"
    teks = re.sub(pola_sendiri, "", teks, count=1, flags=re.I).strip()

    lain = [n for n in semua_nama if n != nama_model]
    if lain:
        alternasi = "|".join(re.escape(n) for n in lain)
        pola_lain = rf"^[ \t]*[*_\[]*(?:{alternasi})[*_\]]*[ \t]*:"
        m = re.search(pola_lain, teks, flags=re.M | re.I)
        if m:
            teks = teks[: m.start()].rstrip()

    return teks, teks != awal

# ================== KLASIFIKASI ERROR ==================
def klasifikasi(e):
    kode = getattr(e, "status_code", None)
    pesan = str(e)
    if kode == 429 or "rate_limit" in pesan:
        return "batas kuota"
    if kode == 413:
        return "permintaan terlalu besar"
    if kode == 404:
        return "model tidak ditemukan / sudah dihentikan"
    if kode == 402:
        return "jatah gratis habis / saldo kosong"
    if kode == 400:
        return "parameter ditolak model"
    if kode in (401, 403):
        return "API key ditolak (cek Secrets / masa aktif kunci)"
    if isinstance(kode, int) and kode >= 500:
        return "server penyedia bermasalah"
    if isinstance(e, APIConnectionError):
        return "koneksi / timeout"
    return "penyebab tidak diketahui"

# ================== PEMANGGIL MODEL + COBA-ULANG OTOMATIS ==================
def panggil_model(penyedia, id_model, konten, nama_model, semua_nama, batasi_reasoning):
    """Mengembalikan dict: teks (None = gagal), penyebab, error (mentah), meta."""
    mulai_total = time.time()
    meta = {"penyedia": penyedia, "id_model": id_model, "percobaan": 0}
    ekstra = PARAM_EKSTRA.get(id_model, {}) if batasi_reasoning else {}
    error, penyebab = "", ""

    for percobaan in range(len(JEDA_COBA_LAG) + 1):
        meta["percobaan"] = percobaan + 1
        mulai = time.time()
        try:
            r = KLIEN[penyedia].chat.completions.create(
                model=id_model,
                messages=[{"role": "user", "content": konten}],
                max_tokens=MAKS_TOKEN_PER_PESAN,
                extra_body=ekstra,
            )
            mentah = r.choices[0].message.content or ""
            teks, berubah = bersihkan_teks(mentah, nama_model, semua_nama)
            meta.update(
                latensi=round(time.time() - mulai, 2),
                token_prompt=r.usage.prompt_tokens if r.usage else None,
                token_output=r.usage.completion_tokens if r.usage else None,
                finish=r.choices[0].finish_reason,  # "length" = terpotong; "content_filter" = diblokir
                dibersihkan=berubah,
                teks_mentah=mentah,
            )
            meta["total_detik"] = round(time.time() - mulai_total, 2)
            if not teks:
                penyebab_kosong = "respons kosong"
                if r.choices[0].finish_reason == "content_filter":
                    penyebab_kosong = "diblokir filter keamanan"
                return {"teks": None, "penyebab": penyebab_kosong, "error": "", "meta": meta}
            return {"teks": teks, "penyebab": "", "error": "", "meta": meta}
        except Exception as e:
            error = str(e)
            penyebab = klasifikasi(e)
            sesak = ("429" in error) or ("413" in error) or ("rate_limit" in error)
            if sesak and percobaan < len(JEDA_COBA_LAG):
                time.sleep(JEDA_COBA_LAG[percobaan])

    meta["total_detik"] = round(time.time() - mulai_total, 2)
    meta["penyebab_error"] = penyebab
    meta["error_mentah"] = error
    return {"teks": None, "penyebab": penyebab, "error": error, "meta": meta}

# ================== STATISTIK & EKSPOR ==================
def hitung_statistik(transkrip):
    baris = {}
    for p in transkrip:
        if p["nama"] == "SISTEM" or p.get("jenis") == "pengamat":
            continue
        s = baris.setdefault(
            p["nama"],
            {"Model": p["nama"], "Penyedia": p.get("penyedia", ""),
             "Pesan": 0, "Gagal": 0, "Terpotong": 0,
             "Rata² kata": 0, "Rata² latensi (dtk)": 0, "Total token": 0,
             "_kata": 0, "_lat": []},
        )
        m = p.get("meta", {})
        if p.get("jenis", "pesan") == "catatan":
            s["Gagal"] += 1
            continue
        s["Pesan"] += 1
        s["_kata"] += len(p["teks"].split())
        if m.get("latensi") is not None:
            s["_lat"].append(m["latensi"])
        s["Total token"] += m.get("token_output") or 0
        if m.get("finish") == "length":
            s["Terpotong"] += 1
    hasil = []
    for s in baris.values():
        s["Rata² kata"] = round(s["_kata"] / s["Pesan"]) if s["Pesan"] else 0
        s["Rata² latensi (dtk)"] = round(sum(s["_lat"]) / len(s["_lat"]), 1) if s["_lat"] else 0
        del s["_kata"], s["_lat"]
        hasil.append(s)
    return hasil

def format_transkrip(transkrip):
    out = []
    for p in transkrip:
        label = "SISTEM" if p.get("jenis", "pesan") == "catatan" else p["nama"]
        out.append(f"[{label}]\n{p['teks']}")
    return "\n\n".join(out)

def ekspor_json(transkrip):
    return json.dumps(
        {
            "sesi_id": st.session_state.sesi_id,
            "konfigurasi": st.session_state.konfigurasi_log,
            "transkrip": transkrip,
        },
        ensure_ascii=False,
        indent=2,
    )

def ekspor_csv(transkrip):
    kolom = ["giliran", "waktu", "jenis", "nama", "penyedia", "id_model", "latensi", "total_detik",
             "token_prompt", "token_output", "finish", "percobaan", "dibersihkan",
             "jumlah_kata", "penyebab_error", "teks"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=kolom, extrasaction="ignore")
    w.writeheader()
    for p in transkrip:
        m = p.get("meta", {})
        baris = {k: m.get(k) for k in kolom}
        baris.update(
            giliran=p.get("giliran"),
            waktu=p.get("waktu"),
            jenis=p.get("jenis", "pesan"),
            nama=p["nama"],
            penyedia=p.get("penyedia", m.get("penyedia", "")),
            teks=p["teks"],
            jumlah_kata=len(p["teks"].split()) if p.get("jenis", "pesan") == "pesan" else "",
        )
        w.writerow(baris)
    return buf.getvalue().encode("utf-8-sig")  # BOM agar terbaca benar di Excel

# ================== TAMPILAN ENTRI ==================
def caption_meta(m):
    if not m:
        return
    bagian = []
    if m.get("latensi") is not None:
        bagian.append(f"⏱️ {m['latensi']} dtk")
    if m.get("token_output") is not None:
        bagian.append(f"{m['token_output']} token")
    if m.get("finish") == "length":
        bagian.append("✂️ terpotong batas token")
    if m.get("percobaan", 1) > 1:
        bagian.append(f"{m['percobaan']}× percobaan")
    if bagian:
        st.caption(" · ".join(bagian))

def tampil_entri(p):
    if p.get("jenis", "pesan") == "catatan":
        if p["nama"] == "SISTEM":
            st.warning(f"⚙️ {p['teks']}")
        else:
            st.caption(f"〰️ ⚠️ {p['teks']}")
    elif p.get("jenis") == "pengamat":
        with st.chat_message("PENGAMAT", avatar="🧑‍🔬"):
            st.markdown("**PENGAMAT** · 🧑‍🔬 *(pesan manusia)*")
            st.markdown(p["teks"])
    else:
        with st.chat_message(p["nama"], avatar=p["tag"]):
            st.markdown(f"**{p['nama']}**")
            st.markdown(p["teks"])
            caption_meta(p.get("meta", {}))

# ================== LAB (SIDEBAR) ==================
with st.sidebar:
    st.header("🔬 Ruang Lab")

    for p, n in NAMA_KUNCI.items():
        if p in PENYEDIA_AKTIF:
            st.caption(f"✅ {p} - kunci siap")
        else:
            st.caption(f"➖ {p} - kunci `{n}` belum terpasang; partisipannya disembunyikan")

    opsi = [n for n in DAFTAR_MODEL if DAFTAR_MODEL[n]["penyedia"] in PENYEDIA_AKTIF]
    terpilih = st.multiselect(
        "Partisipan (nama asli model)",
        opsi,
        default=[d for d in DEFAULT_PARTISIPAN if d in opsi],
    )

    # peringatan bila ID model tidak ada di daftar penyedia + tampilkan kandidat ID asli
    tersedia_cache = {}
    for n in terpilih:
        prov = DAFTAR_MODEL[n]["penyedia"]
        if prov not in tersedia_cache:
            tersedia_cache[prov] = model_tersedia(prov)
        avail = tersedia_cache[prov]
        if avail is None:
            st.caption(f"ℹ️ Daftar model {prov} tidak bisa diambil; ID tidak divalidasi.")
        elif DAFTAR_MODEL[n]["id"] not in avail:
            st.warning(f"⚠️ `{DAFTAR_MODEL[n]['id']}` ({n}) tidak ada di daftar {prov} saat ini.")
            inti = re.split(r"[-/:]", DAFTAR_MODEL[n]["id"].split("/")[-1])[0].lower()
            mirip = sorted(i for i in avail if inti in i.lower())[:6]
            if mirip:
                st.caption("Kandidat ID dari " + prov + ": " +
                           " · ".join(f"`{i}`" for i in mirip))

    if any(DAFTAR_MODEL[n]["penyedia"] == "openrouter" for n in terpilih):
        st.caption("🆓 OpenRouter: gratis maks 20 permintaan/menit, 50/hari (akun tanpa saldo).")

    topik = st.text_input(
        "Pemantik / topik (kosongkan = mode spontan murni)",
        value="",
        placeholder="Contoh: Apakah kecerdasan kolektif bisa lahir dari percakapan antar-AI?",
    )
    jumlah_maks = st.slider("Batas maksimal pesan", 6, 60, 20, step=2)
    batasi_reasoning = st.checkbox(
        "Batasi reasoning model gpt-oss (variabel eksperimen)",
        value=False,
        help="Bila aktif, model gpt-oss memakai reasoning_effort=low sehingga jatah token lebih "
             "banyak untuk jawaban. Pilihan ini dicatat di konfigurasi sesi.",
    )
    st.divider()
    if st.button("▶️ Mulai / Lanjutkan", disabled=st.session_state.sedang_jalan, type="primary"):
        st.session_state.sedang_jalan = True
        st.session_state.gagal_beruntun = 0
    if st.button("⏸️ Jeda", disabled=not st.session_state.sedang_jalan):
        st.session_state.sedang_jalan = False
    if st.button("🧹 Reset sesi"):
        reset_state()
        st.rerun()

    jeda_teks = "/".join(str(j) for j in JEDA_COBA_LAG)
    keterangan = (
        f"Aturan lab: giliran bergilir · konteks {BATAS_KARAKTER_LOG} karakter terakhir · "
        f"maks {MAKS_TOKEN_PER_PESAN} token/pesan · coba ulang setelah {jeda_teks} dtk · "
        f"kegagalan terekam & terlihat semua peserta."
    )
    if BATAS_GAGAL_BERUNTUN:
        keterangan += f" Pemutus otomatis: {BATAS_GAGAL_BERUNTUN} gagal beruntun."
    st.caption(keterangan)

    with st.expander("📊 Statistik sesi", expanded=False):
        statistik = hitung_statistik(st.session_state.transkrip)
        if statistik:
            st.dataframe(statistik, hide_index=True, use_container_width=True)
        else:
            st.caption("Belum ada data.")

    with st.expander("💾 Pulihkan sesi", expanded=False):
        berkas = daftar_autosave()
        if berkas:
            pilihan = st.selectbox("Berkas autosave", berkas, label_visibility="collapsed")
            if st.button("Muat sesi ini", disabled=st.session_state.sedang_jalan):
                muat_sesi(pilihan)
                st.rerun()
        else:
            st.caption("Belum ada berkas autosave.")
        st.caption(f"Sesi aktif: `{st.session_state.sesi_id}`")
        if st.session_state.autosave_error:
            st.warning(f"Autosave gagal menulis: {st.session_state.autosave_error}")

# ================== RUANG PENGAMATAN ==================
st.title("🔬 Room Chat AI")
st.caption("Pengamatan: model-model AI lintas penyedia berdiskusi dan berjalan sendiri - "
           "kegagalan ikut teramati. Intervensi manusia hanya lewat 🚪 Pintu Pengamat, "
           "dan selalu terekam sebagai PENGAMAT.")
st.progress(
    min(st.session_state.giliran / jumlah_maks, 1.0),
    text=f"Giliran {min(st.session_state.giliran, jumlah_maks)}/{jumlah_maks}",
)
st.divider()

if not terpilih:
    st.session_state.sedang_jalan = False
    st.info("Pilih minimal satu partisipan di sidebar.")
    st.stop()

for pesan in st.session_state.transkrip:
    tampil_entri(pesan)

if st.session_state.transkrip:
    kol1, kol2, kol3 = st.columns(3)
    with kol1:
        st.download_button(
            "⬇️ Transkrip (.txt)",
            data=format_transkrip(st.session_state.transkrip),
            file_name=f"transkrip_{st.session_state.sesi_id}.txt",
            mime="text/plain",
        )
    with kol2:
        st.download_button(
            "⬇️ Data lengkap (.json)",
            data=ekspor_json(st.session_state.transkrip),
            file_name=f"data_{st.session_state.sesi_id}.json",
            mime="application/json",
        )
    with kol3:
        st.download_button(
            "⬇️ Tabel metadata (.csv)",
            data=ekspor_csv(st.session_state.transkrip),
            file_name=f"metadata_{st.session_state.sesi_id}.csv",
            mime="text/csv",
        )

# ================== PINTU PENGAMAT (INTERVENSI MANUSIA) ==================
def kirim_pengamat():
    teks = str(st.session_state.get("input_pengamat") or "").strip()
    if not teks:
        return
    tambah_entri({
        "jenis": "pengamat", "giliran": st.session_state.giliran, "waktu": sekarang(),
        "nama": "PENGAMAT", "tag": "🧑‍🔬", "penyedia": "manusia",
        "teks": teks, "meta": {},
    })
    st.session_state.input_pengamat = ""  # kosongkan kotak ketik

if not st.session_state.sedang_jalan:
    with st.container(border=True):
        st.markdown("🚪 **Pintu Pengamat** — selipkan pesanmu ke tengah obrolan. "
                    "Peserta hanya melihatnya sebagai `PENGAMAT: ...`, tanpa penjelasan apa pun.")
        st.text_input("Pesan pengamat", key="input_pengamat", label_visibility="collapsed",
                      placeholder="Ketik pesanmu, lalu klik tombol Masuk...")
        st.button("🚪 Masuk ke ruangan", on_click=kirim_pengamat, type="secondary",
                  disabled=not str(st.session_state.get("input_pengamat") or "").strip())
        st.caption("Gunakan saat sesi dijeda (⏸️). Pesanmu tidak mengambil giliran - "
                   "peserta berikutnya akan membacanya seperti pesan rekan ruangan.")

# ================== MESIN PERCAKAPAN OTOMATIS ==================
if st.session_state.sedang_jalan:
    if st.session_state.giliran >= jumlah_maks:
        st.session_state.sedang_jalan = False
        st.success("🏁 Batas maksimal pesan tercapai. Sesi pengamatan selesai.")
    else:
        catat_konfigurasi_bila_berubah(snapshot_konfigurasi(terpilih, topik, jumlah_maks, batasi_reasoning))

        giliran = st.session_state.giliran
        nama_model = terpilih[giliran % len(terpilih)]
        info = DAFTAR_MODEL[nama_model]
        tag = TAG[list(DAFTAR_MODEL).index(nama_model) % len(TAG)]  # warna tetap per model

        with st.chat_message(nama_model, avatar=tag):
            st.markdown(f"**{nama_model}**")
            slot = st.empty()
            slot.markdown("_sedang merespons..._ ⌨️ (kalau kuota sesak, otomatis menunggu & mencoba lagi)")
            konten = bangun_pengumuman(terpilih, nama_model, topik, bangun_log(st.session_state.transkrip))
            hasil = panggil_model(info["penyedia"], info["id"], konten, nama_model, terpilih, batasi_reasoning)
            if hasil["teks"] is not None:
                slot.markdown(hasil["teks"])
                caption_meta(hasil["meta"])
            else:
                slot.markdown("_(gagal merespons - dicatat sebagai catatan sistem)_")

        if hasil["teks"] is not None:
            st.session_state.gagal_beruntun = 0
            tambah_entri({
                "jenis": "pesan", "giliran": giliran, "waktu": sekarang(),
                "nama": nama_model, "tag": tag, "penyedia": info["penyedia"],
                "teks": hasil["teks"], "meta": hasil["meta"],
            })
        else:
            st.session_state.gagal_beruntun += 1
            if TAMPILKAN_ERROR_LENGKAP:
                ringkas = hasil["error"][:300] + ("…" if len(hasil["error"]) > 300 else "")
                teks_catatan = (f"{nama_model} gagal merespons ({hasil['penyebab']}). "
                                f"Detail teknis: {ringkas} - giliran dilewati.")
            else:
                teks_catatan = (f"{nama_model} gagal merespons ({hasil['penyebab']}). "
                                f"Pesannya tidak terkirim - giliran dilewati.")
            hasil["meta"].setdefault("penyebab_error", hasil["penyebab"])
            hasil["meta"].setdefault("error_mentah", hasil["error"])
            tambah_entri({
                "jenis": "catatan", "giliran": giliran, "waktu": sekarang(),
                "nama": nama_model, "tag": tag, "penyedia": info["penyedia"],
                "teks": teks_catatan, "meta": hasil["meta"],
            })

        # pemutus otomatis
        if BATAS_GAGAL_BERUNTUN and st.session_state.gagal_beruntun >= BATAS_GAGAL_BERUNTUN:
            st.session_state.sedang_jalan = False
            tambah_entri({
                "jenis": "catatan", "giliran": giliran, "waktu": sekarang(),
                "nama": "SISTEM", "tag": "⚙️", "meta": {},
                "teks": (f"Sesi dijeda otomatis setelah {BATAS_GAGAL_BERUNTUN} kegagalan berturut-turut "
                         f"(kemungkinan kuota habis atau layanan bermasalah). "
                         f"Tekan Mulai / Lanjutkan untuk meneruskan."),
            })

        st.session_state.giliran += 1
        time.sleep(1.5)
        st.rerun()
