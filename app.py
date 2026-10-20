import time
import streamlit as st
from groq import Groq

# ================== PENGATURAN HALAMAN ==================
st.set_page_config(page_title="Arena Obrolan AI", page_icon="🥊", layout="wide")

# ================== DAFTAR MODEL (PEMAIN ARENA) ==================
# Kalau nanti ada model yang error "decommissioned", ganti ID-nya
# dengan model terbaru dari: https://console.groq.com/docs/models
MODELS = {
    "GPT-OSS 120B (Kakak Pintar)": "openai/gpt-oss-120b",
    "GPT-OSS 20B (Si Kilat)": "openai/gpt-oss-20b",
    "Qwen 3.8 27B (Penantang)": "qwen/qwen3.8-27b",
}

# ================== RIWAYAT OBROLAN ==================
if "riwayat" not in st.session_state:
    st.session_state.riwayat = []

# ================== KONEKSI KE GROQ ==================
# API Key diambil dari "Secrets" — BUKAN ditulis di kode, biar aman!
try:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
except Exception:
    st.error("🔑 API Key Groq belum dipasang! Nanti kita pasang lewat menu Settings → Secrets di Streamlit Cloud.")
    st.stop()

# ================== TAMPILAN UTAMA ==================
st.title("🥊 Arena Obrolan AI")
st.caption("Satu pertanyaan, tiga otak AI menjawab berdampingan — gratis lewat Groq Cloud.")

with st.sidebar:
    st.header("⚙️ Pengaturan")
    peran_ai = st.text_area(
        "Peran AI (system prompt)",
        value="Kamu asisten AI yang ramah. Jawab dengan bahasa yang mudah dipahami pemula.",
    )
    kreativitas = st.slider("Kreativitas (temperature)", 0.0, 1.5, 0.7, 0.1)
    panjang_maks = st.slider("Panjang jawaban maksimal (token)", 256, 8192, 2048, 128)
    st.divider()
    if st.session_state.riwayat and st.button("🧹 Hapus riwayat obrolan"):
        st.session_state.riwayat = []
        st.rerun()
    st.caption("Dibuat dengan Streamlit + Groq Cloud 🚀")

# ================== KOTAK PERTANYAAN ==================
with st.form("form_arena", clear_on_submit=True):
    pertanyaan = st.text_area(
        "💬 Tulis pertanyaanmu — nanti dijawab barengan sama ketiganya:",
        placeholder="Contoh: Jelaskan apa itu black hole untuk anak SMA dalam 3 kalimat",
        height=100,
    )
    kirim = st.form_submit_button("🚀 Tanya Ketiga AI!")

# ================== PROSES & SIMPAN JAWABAN ==================
if kirim and pertanyaan.strip():
    hasil_ronde = {}
    with st.spinner("Ketiga AI sedang mikir... 🤔"):
        for nama_model, id_model in MODELS.items():
            mulai = time.time()
            try:
                respons = client.chat.completions.create(
                    model=id_model,
                    messages=[
                        {"role": "system", "content": peran_ai},
                        {"role": "user", "content": pertanyaan},
                    ],
                    temperature=kreativitas,
                    max_tokens=panjang_maks,
                )
                teks = respons.choices[0].message.content or "(model tidak memberi jawaban)"
                hasil_ronde[nama_model] = {"teks": teks, "detik": time.time() - mulai, "error": None}
            except Exception as e:
                hasil_ronde[nama_model] = {"teks": "", "detik": time.time() - mulai, "error": str(e)}
    st.session_state.riwayat.append({"tanya": pertanyaan, "jawaban": hasil_ronde})

# ================== TAMPILKAN OBROLAN ==================
for ronde in st.session_state.riwayat:
    st.markdown(f"#### 🧑‍💻 **Kamu:** {ronde['tanya']}")
    kolom = st.columns(len(ronde["jawaban"]))
    for kol, (nama_model, hasil) in zip(kolom, ronde["jawaban"].items()):
        with kol:
            with st.container(border=True):
                st.markdown(f"🤖 **{nama_model}** · ⏱️ {hasil['detik']:.1f} dtk")
                if hasil["error"]:
                    st.error(hasil["error"])
                else:
                    st.markdown(hasil["teks"])
    st.divider()
