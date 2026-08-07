import streamlit as st
from supabase import create_client, Client
from datetime import datetime
import pytz

# Configuração do Fuso Horário do Brasil
FUSO_BR = pytz.timezone('America/Recife')

def obter_data_hora_atual():
    """Retorna a data e hora formatada no fuso de Brasília/Recife (DD/MM/YYYY HH:MM:SS)"""
    return datetime.now(FUSO_BR).strftime('%d/%m/%Y %H:%M:%S')

# Configuração da página Streamlit
st.set_page_config(
    page_title="Controle de Acesso - Portaria QCG",
    page_icon="🛡️",
    layout="wide"
)

# Conexão com o Supabase
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# Autenticação de Usuários Simples
USUARIOS = {
    "sentinela": "qcg2026",
    "admin": "coronel2026"
}

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🛡️ Controle de Acesso - Portaria QCG")
    st.subheader("Acesso ao Sistema")
    
    usuario_input = st.text_input("Usuário")
    senha_input = st.text_input("Senha", type="password")
    
    if st.button("Entrar"):
        if usuario_input in USUARIOS and USUARIOS[usuario_input] == senha_input:
            st.session_state.logged_in = True
            st.session_state.usuario = usuario_input
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()

# --- TELA PRINCIPAL DO SISTEMA ---
st.title("🛡️ Controle de Acesso - Portaria QCG")
st.caption(f"Usuário ativo: **{st.session_state.usuario}** | {obter_data_hora_atual()}")

# Abas de Funcionalidades
aba1, aba2, aba3 = st.tabs(["🚗 Registro de Movimentação", "📋 Cadastro de Veículos/Pessoas", "📊 Histórico Geral"])

# -------------------------------------------------------------
# ABA 1: REGISTRO DE MOVIMENTAÇÃO (ENTRADA / SAÍDA)
# -------------------------------------------------------------
with aba1:
    st.header("Entrada e Saída de Veículos")
    placa_busca = st.text_input("Digite a Placa do Veículo:").strip().upper()
    
    if placa_busca:
        # Busca no cadastro prévio
        res_cad = supabase.table("cadastros").select("*").eq("placa", placa_busca).execute()
        
        if res_cad.data:
            dados = res_cad.data[0]
            st.success("Veículo Encontrado no Cadastro!")
            st.write(f"**Placa:** {dados.get('placa')}")
            st.write(f"**Posto/Cargo:** {dados.get('posto_cargo', 'N/I')}")
            st.write(f"**Nome:** {dados.get('nome', 'N/I')}")
            st.write(f"**Obs:** {dados.get('obs', 'Sem observações')}")
            
            # Verificar se há entrada em aberto sem saída
            res_mov = supabase.table("movimentacoes")\
                .select("*")\
                .eq("placa", placa_busca)\
                .eq("status", "Em Trânsito")\
                .execute()
                
            if res_mov.data:
                mov_aberta = res_mov.data[0]
                st.warning(f"Veículo com entrada em aberto desde: {mov_aberta.get('hora_entrada')}")
                if st.button("🔴 Confirmar Saída do Veículo", type="primary"):
                    hora_saida = obter_data_hora_atual()
                    supabase.table("movimentacoes").update({
                        "hora_saida": hora_saida,
                        "status": "Concluído"
                    }).eq("id", mov_aberta["id"]).execute()
                    st.success("Saída registrada com sucesso!")
                    st.rerun()
            else:
                if st.button("🟢 Confirmar Entrada do Veículo", type="primary"):
                    hora_entrada = obter_data_hora_atual()
                    supabase.table("movimentacoes").insert({
                        "placa": placa_busca,
                        "nome": dados.get("nome"),
                        "posto_cargo": dados.get("posto_cargo"),
                        "hora_entrada": hora_entrada,
                        "status": "Em Trânsito"
                    }).execute()
                    st.success("Entrada registrada com sucesso!")
                    st.rerun()
        else:
            st.warning("Veículo Não Cadastrado! Preencha as informações para registro avulso:")
            with st.form("form_avulso"):
                nome_avulso = st.text_input("Nome do Condutor")
                posto_avulso = st.text_input("Posto/Cargo ou Documento/Empresa")
                btn_reg_avulso = st.form_submit_button("🟢 Confirmar Entrada Avulsa")
                
                if btn_reg_avulso:
                    hora_entrada = obter_data_hora_atual()
                    supabase.table("movimentacoes").insert({
                        "placa": placa_busca,
                        "nome": nome_avulso,
                        "posto_cargo": posto_avulso,
                        "hora_entrada": hora_entrada,
                        "status": "Em Trânsito"
                    }).execute()
                    st.success("Entrada Avulsa registrada com sucesso!")
                    st.rerun()

    st.divider()
    st.subheader("📑 Movimentação em Tempo Real")
    movs = supabase.table("movimentacoes").select("*").order("created_at", desc=True).limit(20).execute()
    if movs.data:
        st.dataframe(movs.data, use_container_width=True)
    else:
        st.info("Nenhuma movimentação registrada até o momento.")

# -------------------------------------------------------------
# ABA 2: CADASTRO DE VEÍCULOS E PESSOAS
# -------------------------------------------------------------
with aba2:
    st.header("Novo Cadastro de Veículo / Pessoa")
    with st.form("form_novo_cadastro"):
        placa_cad = st.text_input("Placa do Veículo").strip().upper()
        nome_cad = st.text_input("Nome Completo")
        posto_cad = st.text_input("Posto / Graduação / Cargo")
        obs_cad = st.text_area("Observações (ex: Setor, Telefone, Autorização)")
        btn_salvar_cad = st.form_submit_button("💾 Salvar Cadastro")
        
        if btn_salvar_cad:
            if placa_cad and nome_cad:
                supabase.table("cadastros").insert({
                    "placa": placa_cad,
                    "nome": nome_cad,
                    "posto_cargo": posto_cad,
                    "obs": obs_cad
                }).execute()
                st.success(f"Cadastro da placa {placa_cad} realizado com sucesso!")
            else:
                st.error("Por favor, preencha pelo menos a Placa e o Nome.")

# -------------------------------------------------------------
# ABA 3: HISTÓRICO GERAL
# -------------------------------------------------------------
with aba3:
    st.header("Histórico Completo")
    todas_movs = supabase.table("movimentacoes").select("*").order("created_at", desc=True).execute()
    if todas_movs.data:
        st.dataframe(todas_movs.data, use_container_width=True)
    else:
        st.info("Nenhum histórico encontrado.")
