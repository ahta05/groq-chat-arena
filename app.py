import time
import streamlit as st
from groq import Groq

# ================== PENGATURAN HALAMAN ==================
st.set_page_config(page_title="Room Chat AI — Eksperimen", page_icon="🔬", layout="wide")

# ================== PARTISIPAN (NAMA ASLI MODEL GROQ) ==================
# Tambah/kurangi peserta di sini. Daftar ID resmi: https://console.groq.com/models
DAFTAR_MODEL = {
    "GPT-OSS 120B": "openai/gpt-oss-120b",
    "GPT-OSS 20B": "openai/gpt-oss-20b",
    "GPT-OSS Safeguard 20B": "openai/gpt-oss-safeguard-20b",
    "Qwen 3.8 27B": "qwen/qwen3.8-27b",
    "Kimi K2": "moonshotai/kimi-k2-instruct",   # opsional — kalau selalu gagal, hapus barisnya
    "ALLAM 2 7B": "allam-2-7b",                  # opsional — condong bahasa Arab
}
TAG = ["🟦", "🟨", "🟥", "🟩", "🟪", "🟧"]   # penanda visual, bukan identitas
TAMPILKAN_ERROR_LENGKAP = False  # ganti True kalau mau error mentah ikut tercatat

# ================== ATURAN LAB ==================
MAKS_TOKEN_PER_PESAN = 800   # batas panjang 1 pesan — patuh kuota gratis Groq
BATAS_KARAKTER_LOG = 5000    # memori konteks: 5000 karakter terakhir
JEDA_COBA_LAG = [10, 20]     # kalau kuota sesak: tunggu 10 dtk, lalu 20 dtk, coba lagi

# ================== MESIN STATE ==================
if "transkrip" not in st.session_state:
    st.session_state.transkrip = []
if "sedang_jalan" not in st.session_state:
    st.session_state.sedang_jalan = False
if "giliran" not in st.session_state:
    st.session_state.giliran = 0

# ================== KONEKSI KE GROQ ==================
try:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
except Exception:
    st.error("🔑 API Key Groq belum dipasang! Buka Manage app → Settings → Secrets.")
    st.stop()

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
    return "\n\n".join(baris_terpilih) or "(percakapan belum dimulai — Anda peserta pertama yang bicara)"

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
        f"(ini ruang chat, bukan dokumen — tanpa judul/tabel/daftar panjang).\n"
        f"Baris berawalan [SISTEM] adalah catatan teknis ruangan, bukan pesan peserta.\n"
        f"Jangan menulis nama Anda di awal pesan, dan jangan menulis pesan atas nama model lain."
    )

# ================== PEMANGGIL MODEL + COBA-ULANG OTOMATIS ==================
def panggil_model(id_model, konten):
    error = ""
    for percobaan in range(len(JEDA_COBA_LAG) + 1):
        try:
            respons = client.chat.completions.create(
                model=id_model,
                messages=[{"role": "user", "content": konten}],
                max_tokens=MAKS_TOKEN_PER_PESAN,
            )
            return (respons.choices[0].message.content or "...").strip(), ""
        except Exception as e:
            error = str(e)
            sesak = ("429" in error) or ("413" in error) or ("rate_limit" in error)
            if sesak and percobaan < len(JEDA_COBA_LAG):
                time.sleep(JEDA_COBA_LAG[percobaan])
    return None, error

# ================== LAB (SIDEBAR) ==================
with st.sidebar:
    st.header("🔬 Ruang Lab")
    terpilih = st.multiselect(
        "Partisipan (nama asli model)",
        list(DAFTAR_MODEL.keys()),
        default=["GPT-OSS 120B", "GPT-OSS 20B", "Qwen 3.8 27B"],
    )
    topik = st.text_input(
        "Pemantik / topik (kosongkan = mode spontan murni)",
        value="",
        placeholder="Contoh: Apakah kecerdasan kolektif bisa lahir dari percakapan antar-AI?",
    )
    jumlah_maks = st.slider("Batas maksimal pesan", 6, 60, 20, step=2)
    st.divider()
    if st.button("▶️ Mulai / Lanjutkan", disabled=st.session_state.sedang_jalan, type="primary"):
        st.session_state.sedang_jalan = True
    if st.button("⏸️ Jeda", disabled=not st.session_state.sedang_jalan):
        st.session_state.sedang_jalan = False
    if st.button("🧹 Reset sesi"):
        st.session_state.transkrip = []
        st.session_state.sedang_jalan = False
        st.session_state.giliran = 0
        st.rerun()
    st.caption("Aturan lab: giliran bergilir · konteks 5000 karakter terakhir · maks 800 token/pesan · kegagalan terekam & terlihat semua peserta.")

# ================== RUANG PENGAMATAN ==================
st.title("🔬 Room Chat AI")
st.caption("Pengamatan: model-model AI berdiskusi tanpa intervensi manusia — nama asli, kepribadian alami, kegagalan ikut teramati.")
st.divider()

if not terpilih:
    st.session_state.sedang_jalan = False
    st.info("Pilih minimal satu partisipan di sidebar.")
    st.stop()

for pesan in st.session_state.transkrip:
    if pesan.get("jenis", "pesan") == "catatan":
        st.caption(f"〰️ ⚠️ {pesan['teks']}")
    else:
        with st.chat_message(pesan["nama"], avatar=pesan["tag"]):
            st.markdown(f"**{pesan['nama']}**")
            st.markdown(pesan["teks"])

if st.session_state.transkrip:
    st.download_button(
        "⬇️ Unduh transkrip (.txt) — untuk arsip penelitian",
        data="\n\n".join([f"[{p['nama']}]\n{p['teks']}" for p in st.session_state.transkrip]),
        file_name="transkrip_room_chat_ai.txt",
        mime="text/plain",
    )

# ================== MESIN PERCAKAPAN OTOMATIS ==================
if st.session_state.sedang_jalan:
    if st.session_state.giliran >= jumlah_maks:
        st.session_state.sedang_jalan = False
        st.success("🏁 Batas maksimal pesan tercapai. Sesi pengamatan selesai.")
    else:
        nama_model = terpilih[st.session_state.giliran % len(terpilih)]
        id_model = DAFTAR_MODEL[nama_model]
        tag = TAG[terpilih.index(nama_model) % len(TAG)]
        with st.chat_message(nama_model, avatar=tag):
            st.markdown(f"**{nama_model}**")
            slot = st.empty()
            slot.markdown("_sedang merespons..._ ⌨️ (kalau kuota sesak, otomatis menunggu & mencoba lagi)")
            konten = bangun_pengumuman(terpilih, nama_model, topik, bangun_log(st.session_state.transkrip))
            teks, error = panggil_model(id_model, konten)
            if teks is not None:
                slot.markdown(teks)
        if teks is not None:
            st.session_state.transkrip.append({"jenis": "pesan", "nama": nama_model, "tag": tag, "teks": teks})
        else:
            if TAMPILKAN_ERROR_LENGKAP:
                ringkas = error[:300] + ("…" if len(error) > 300 else "")
                teks_catatan = f"{nama_model} gagal merespons. Detail teknis: {ringkas} — giliran dilewati."
            else:
                teks_catatan = f"{nama_model} gagal merespons (diduga kena batas kuota). Pesannya tidak terkirim — giliran dilewati."
            st.session_state.transkrip.append({"jenis": "catatan", "nama": nama_model, "tag": tag, "teks": teks_catatan})
        st.session_state.giliran += 1
        time.sleep(1.5)
        st.rerun()
