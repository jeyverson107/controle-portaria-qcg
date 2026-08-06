import streamlit as st
from supabase import create_client, Client

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Portaria QCG", page_icon="🛡️", layout="centered")

# --- CONEXÃO COM O SUPABASE ---
URL_SUPABASE = st.secrets.get("SUPABASE_URL", "")
CHAVE_SUPABASE = st.secrets.get("SUPABASE_KEY", "")

@st.cache_resource
def iniciar_conexao():
    if URL_SUPABASE and CHAVE_SUPABASE:
        return create_client(URL_SUPABASE, CHAVE_SUPABASE)
    return None

supabase: Client = iniciar_conexao()

# --- SISTEMA DE LOGIN DE DEMONSTRAÇÃO ---
USUARIOS = {
    "sentinela": "qcg2026",
    "admin": "coronel2026"
}

if "logado" not in st.session_state:
    st.session_state["logado"] = False

st.title("🛡️ Controle de Acesso - Portaria QCG")

if not st.session_state["logado"]:
    st.subheader("Acesso ao Sistema")
    usuario_input = st.text_input("Usuário")
    senha_input = st.text_input("Senha", type="password")
    
    if st.button("Entrar", type="primary"):
        if usuario_input in USUARIOS and USUARIOS[usuario_input] == senha_input:
            st.session_state["logado"] = True
            st.session_state["usuario_atual"] = usuario_input
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
else:
    st.sidebar.markdown(f"**Militar em serviço:** `{st.session_state['usuario_atual']}`")
    if st.sidebar.button("Sair / Trocar Turno"):
        st.session_state["logado"] = False
        st.rerun()

    st.success("Sentinela autenticado.")
    
    # --- FORMULÁRIO DE REGISTRO ---
    with st.form("form_registro", clear_on_submit=True):
        st.subheader("Registrar Entrada/Saída de Veículo")
        
        placa = st.text_input("Placa do Veículo (ex: ABC1D23)").upper()
        motorista = st.text_input("Nome / Posto ou Graduação / Entidade")
        observacao = st.text_area("Observação (Ex: Coronel, DAJA, Autorizado por...)")
        
        submeter = st.form_submit_button("Salvar Registro", type="primary")

        if submeter:
            if not placa or not motorista:
                st.warning("Por favor, preencha pelo menos a Placa e o Motorista/Autoridade.")
            else:
                dados = {
                    "placa": placa,
                    "motorista": motorista,
                    "observacao": observacao,
                    "usuario_registro": st.session_state["usuario_atual"]
                }
                
                if supabase:
                    try:
                        supabase.table("controle_portaria_qcg").insert(dados).execute()
                        st.success(f"Registro do veículo {placa} salvo com sucesso!")
                    except Exception as e:
                        st.error(f"Erro ao salvar no banco: {e}")
                else:
                    st.info("Banco de dados pronto. Conectaremos o link do Supabase na publicação final.")

    # --- EXIBIÇÃO DOS REGISTROS ---
    st.divider()
    st.subheader("📋 Registros Recentes")
    if supabase:
        try:
            resposta = supabase.table("controle_portaria_qcg").select("*").order("created_at", desc=True).limit(10).execute()
            if resposta.data:
                st.dataframe(resposta.data, use_container_width=True)
            else:
                st.info("Nenhum registro encontrado ainda.")
        except Exception as e:
            st.write("Aguardando sincronização inicial.")
