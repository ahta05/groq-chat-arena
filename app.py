import time
import streamlit as st
from groq import Groq

# ================== PENGATURAN HALAMAN ==================
st.set_page_config(page_title="Room Chat AI", page_icon="💬", layout="wide")

# ================== DAFTAR OTAK (MODEL GROQ) ==================
# Kalau ada model yang error "decommissioned", ganti ID-nya dengan
# model terbaru dari: https://console.groq.com/docs/models
DAFTAR_MODEL = {
    "GPT-OSS 120B (Kakak Pintar)": "openai/gpt-oss-120b",
    "GPT-OSS 20B (Si Kilat)": "openai/gpt-oss-20b",
    "Qwen 3.8 27B (Penantang)": "qwen/qwen3.8-27b",
}

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

# ================== OTAK KARAKTER ==================
def generate_kalimat(pembicara, semua_karakter, topik, transkrip):
    nm = pembicara["nama"]
    log_terakhir = transkrip[-10:]  # hemat kuota: cukup kirim 10 pesan terakhir
    log = "\n".join([f"{p['nama']}: {p['teks']}" for p in log_terakhir]) or "(belum ada pesan)"
    daftar_nama = ", ".join(k["nama"] for k in semua_karakter)
    prompt_sistem = f"""Kamu adalah "{nm}", salah satu anggota grup chat.
Kepribadianmu: {pembicara['kepribadian']}
Anggota grup lainnya: {daftar_nama}.
Topik obrolan: {topik}

ATURAN:
1. Tulis HANYA satu pesan singkat (maksimal 2-3 kalimat) sebagai dirimu.
2. Jangan menulis nama siapa pun di awal pesan, dan jangan menulis pesan untuk karakter lain.
3. Nyambung dengan obrolan sebelumnya: boleh setuju, berdebat, bertanya, atau melucu.
4. Gaya bahasa santai seperti orang ngobrol di grup chat."""
    isi_user = (
        f"Transkrip obrolan sejauh ini:\n\n{log}\n\n"
        f"Sekarang giliranmu. Tulis pesan berikutnya sebagai {nm} — tanpa label nama, langsung isinya saja."
    )
    respons = client.chat.completions.create(
        model=pembicara["model"],
        messages=[
            {"role": "system", "content": prompt_sistem},
            {"role": "user", "content": isi_user},
        ],
        temperature=0.9,
        max_tokens=512,
    )
    return (respons.choices[0].message.content or "...").strip()

# ================== SUSUNAN KARAKTER (SIDEBAR) ==================
KARAKTER_DEFAULT = [
    {"nama": "Raka", "emoji": "🦊", "kepribadian": "Praktis dan logis. Suka data, langsung ke inti, kadang sarkas tapi ramah."},
    {"nama": "Lulu", "emoji": "🐼", "kepribadian": "Kreatif dan penuh rasa penasaran. Suka metafora dan sudut pandang tak terduga."},
    {"nama": "Ben", "emoji": "🦉", "kepribadian": "Skeptis dan kritis. Suka menguji argumen orang lain dengan pertanyaan tajam."},
]

with st.sidebar:
    st.header("🎭 Susun Karaktermu")
    karakter = []
    for i in range(3):
        with st.expander(f"Karakter {i + 1}", expanded=(i == 0)):
            nama = st.text_input("Nama", value=KARAKTER_DEFAULT[i]["nama"], key=f"nama{i}")
            emoji = st.selectbox("Avatar", ["🦊", "🐼", "🦉", "🐙", "🦁", "🐨", "🐢", "🦜"], index=i, key=f"emoji{i}")
            model_label = st.selectbox("Otak (model)", list(DAFTAR_MODEL.keys()), index=i, key=f"model{i}")
            kepribadian = st.text_area("Kepribadian", value=KARAKTER_DEFAULT[i]["kepribadian"], key=f"pers{i}", height=90)
        karakter.append({"nama": nama.strip() or f"Karakter {i + 1}", "emoji": emoji,
                         "model": DAFTAR_MODEL[model_label], "kepribadian": kepribadian})

    st.header("🎬 Kontrol Eksperimen")
    topik = st.text_input("Topik obrolan",
                          value="Apakah AI akan menggantikan pekerjaan manusia dalam 10 tahun ke depan?")
    jumlah_maks = st.slider("Maksimal jumlah pesan", 6, 40, 18, step=2)
    st.divider()
    if st.button("▶️ Mulai / Lanjutkan", disabled=st.session_state.sedang_jalan, type="primary"):
        st.session_state.sedang_jalan = True
    if st.button("⏸️ Jeda", disabled=not st.session_state.sedang_jalan):
        st.session_state.sedang_jalan = False
    if st.button("🧹 Reset ruang obrolan"):
        st.session_state.transkrip = []
        st.session_state.sedang_jalan = False
        st.session_state.giliran = 0
        st.rerun()
    st.caption("Eksperimen: AI mengobrol tanpa campur tangan manusia 🤖")

# ================== TAMPILAN RUANG OBROLAN ==================
st.title("💬 Room Chat AI")
st.caption("Eksperimen: beberapa model AI saling mengobrol otomatis — kamu cuma jadi pengamat 👀")
st.divider()

if st.session_state.sedang_jalan:
    st.caption("🟢 Obrolan sedang berjalan otomatis — tekan ⏸️ Jeda di sidebar kalau mau berhenti")
else:
    st.caption("⏸️ Obrolan sedang dijeda / belum dimulai")

for pesan in st.session_state.transkrip:
    with st.chat_message(pesan["emoji"], avatar=pesan["emoji"]):
        st.markdown(f"**{pesan['nama']}**")
        st.markdown(pesan["teks"])

# ================== MESIN PERCAKAPAN OTOMATIS ==================
if st.session_state.sedang_jalan:
    if not topik.strip():
        st.warning("⚠️ Tulis topik obrolan dulu di sidebar ya!")
        st.session_state.sedang_jalan = False
        st.stop()
    if st.session_state.giliran >= jumlah_maks:
        st.session_state.sedang_jalan = False
        st.success("🏁 Obrolan selesai! Batas maksimal pesan sudah tercapai.")
    else:
        pembicara = karakter[st.session_state.giliran % len(karakter)]
        with st.chat_message(pembicara["emoji"], avatar=pembicara["emoji"]):
            st.markdown(f"**{pembicara['nama']}**")
            slot = st.empty()
            slot.markdown("_sedang menulis..._ ⌨️")
            try:
                teks = generate_kalimat(pembicara, karakter, topik, st.session_state.transkrip)
            except Exception as e:
                teks = f"⚠️ Gagal memanggil model: {e}"
            slot.markdown(teks)
        st.session_state.transkrip.append({"nama": pembicara["nama"], "emoji": pembicara["emoji"], "teks": teks})
        st.session_state.giliran += 1
        time.sleep(1.5)  # jeda biar terasa natural kayak orang lagi ngetik
        st.rerun()
