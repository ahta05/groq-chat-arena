import time
import streamlit as st
from groq import Groq

# ================== PENGATURAN HALAMAN ==================
st.set_page_config(page_title="Room Chat AI — Eksperimen", page_icon="🔬", layout="wide")

# ================== PARTISIPAN (NAMA ASLI MODEL GROQ) ==================
# Sesuai protokol penelitian: nama asli, tanpa julukan, tanpa rekayasa kepribadian.
# Kalau ada model error "decommissioned", ganti ID dari: https://console.groq.com/docs/models
DAFTAR_MODEL = {
    "GPT-OSS 120B": "openai/gpt-oss-120b",
    "GPT-OSS 20B": "openai/gpt-oss-20b",
    "Qwen 3.8 27B": "qwen/qwen3.8-27b",
}
TAG = ["🟦", "🟨", "🟥"]  # cuma penanda visual biar gampang dilacak mata kita — bukan identitas

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
    st.error("🔑 API Key Groq belum dipasang! Nanti kita pasang lewat Settings → Secrets di Streamlit Cloud.")
    st.stop()

# ================== PENGUMUMAN SITUASI (SATU-SATUNYA "PAPAN PENGUMUMAN") ==================
# Isinya HANYA info kondisi ruangan — tanpa dikte kepribadian/gaya/pendirian.
def bangun_pengumuman(daftar_partisipan, nama_model, topik, transkrip):
    semua_nama = ", ".join(daftar_partisipan)
    if transkrip:
        log = "\n".join([f"{p['nama']}: {p['teks']}" for p in transkrip[-10:]])
    else:
        log = "(percakapan belum dimulai — Anda peserta pertama yang bicara)"
    if topik.strip():
        baris_topik = f"Topik diskusi: {topik.strip()}"
    else:
        baris_topik = "Tidak ada topik yang ditetapkan. Perlakukan ini sebagai percakapan terbuka."
    return (
        f"Anda adalah {nama_model}, sebuah model AI. Anda berpartisipasi dalam percakapan grup "
        f"bersama model AI lainnya: {semua_nama}. {baris_topik}\n\n"
        f"Percakapan sejauh ini:\n\n{log}\n\n"
        f"Sekarang giliran Anda. Tulis SATU pesan berikutnya sebagai {nama_model}, "
        f"dengan kemampuan terbaik dan gaya komunikasi Anda sendiri. "
        f"Jangan menulis nama Anda di awal pesan, dan jangan menulis pesan atas nama model lain."
    )

# ================== LAB (SIDEBAR) ==================
with st.sidebar:
    st.header("🔬 Ruang Lab")
    terpilih = st.multiselect(
        "Partisipan (nama asli model)",
        list(DAFTAR_MODEL.keys()),
        default=list(DAFTAR_MODEL.keys()),
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
    st.caption("Kesadaran partisipan atas ruangan berasal dari pengumuman situasi — bukan dikte kepribadian.")

# ================== RUANG PENGAMATAN ==================
st.title("🔬 Room Chat AI")
st.caption("Pengamatan: model-model AI berdiskusi tanpa intervensi manusia — nama asli, kepribadian alami.")
st.divider()

if not terpilih:
    st.session_state.sedang_jalan = False
    st.info("Pilih minimal satu partisipan di sidebar.")
    st.stop()

for pesan in st.session_state.transkrip:
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
        with st.chat_message(nama_model, avatar=TAG[terpilih.index(nama_model) % len(TAG)]):
            st.markdown(f"**{nama_model}**")
            slot = st.empty()
            slot.markdown("_sedang merespons..._ ⌨️")
            try:
                respons = client.chat.completions.create(
                    model=id_model,
                    messages=[
                        {"role": "user",
                         "content": bangun_pengumuman(terpilih, nama_model, topik, st.session_state.transkrip)},
                    ],
                    max_tokens=2048,
                )
                teks = (respons.choices[0].message.content or "...").strip()
            except Exception as e:
                teks = f"⚠️ Gagal memanggil model: {e}"
            slot.markdown(teks)
        st.session_state.transkrip.append(
            {"nama": nama_model, "tag": TAG[terpilih.index(nama_model) % len(TAG)], "teks": teks}
        )
        st.session_state.giliran += 1
        time.sleep(1.5)  # jeda antar pesan biar alami
        st.rerun()
