import io
import datetime
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from supabase import create_client, Client

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Portaria QCG", page_icon="🛡️", layout="wide")

# --- CONEXÃO COM O SUPABASE ---
URL_SUPABASE = st.secrets.get("SUPABASE_URL", "")
CHAVE_SUPABASE = st.secrets.get("SUPABASE_KEY", "")

@st.cache_resource
def iniciar_conexao():
    if URL_SUPABASE and CHAVE_SUPABASE:
        return create_client(URL_SUPABASE, CHAVE_SUPABASE)
    return None

supabase: Client = iniciar_conexao()

# --- SISTEMA DE LOGIN ---
USUARIOS = {
    "sentinela": "qcg2026",
    "admin": "coronel2026"
}

if "logado" not in st.session_state:
    st.session_state["logado"] = False
if "placa_prefill" not in st.session_state:
    st.session_state["placa_prefill"] = ""

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
    st.stop()

# --- BARRA LATERAL ---
st.sidebar.markdown(f"**Militar em serviço:** `{st.session_state['usuario_atual']}`")
if st.sidebar.button("Sair / Trocar Turno"):
    st.session_state["logado"] = False
    st.rerun()

# --- FUNÇÕES DE BANCO DE DADOS ---
if "veiculos_db" not in st.session_state:
    st.session_state["veiculos_db"] = []
if "movimentacoes_db" not in st.session_state:
    st.session_state["movimentacoes_db"] = []

def buscar_veiculo(placa):
    placa = placa.strip().upper()
    if supabase:
        try:
            res = supabase.table("cadastros_veiculos").select("*").eq("placa", placa).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass
    for v in st.session_state["veiculos_db"]:
        if v["placa"] == placa:
            return v
    return None

def salvar_veiculo(placa, posto, nome, observacao):
    dados = {
        "placa": placa.strip().upper(),
        "posto": posto,
        "nome": nome,
        "observacao": observacao
    }
    if supabase:
        try:
            supabase.table("cadastros_veiculos").upsert(dados, on_conflict="placa").execute()
        except Exception:
            pass
    st.session_state["veiculos_db"] = [v for v in st.session_state["veiculos_db"] if v["placa"] != dados["placa"]]
    st.session_state["veiculos_db"].append(dados)

def registrar_entrada(placa, posto, nome, observacao):
    hora_atual = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    dados = {
        "placa": placa.strip().upper(),
        "posto": posto,
        "nome": nome,
        "observacao": observacao,
        "hora_entrada": hora_atual,
        "hora_saida": "Em Patio",
        "usuario": st.session_state["usuario_atual"]
    }
    if supabase:
        try:
            supabase.table("movimentacoes_portaria").insert(dados).execute()
        except Exception:
            pass
    dados["id"] = len(st.session_state["movimentacoes_db"]) + 1
    st.session_state["movimentacoes_db"].append(dados)

def registrar_saida(registro_id, placa, hora_entrada):
    hora_saida = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    if supabase:
        try:
            supabase.table("movimentacoes_portaria").update({"hora_saida": hora_saida}).eq("placa", placa).eq("hora_entrada", hora_entrada).execute()
        except Exception:
            pass
    for m in st.session_state["movimentacoes_db"]:
        if m.get("id") == registro_id or (m["placa"] == placa and m["hora_entrada"] == hora_entrada):
            m["hora_saida"] = hora_saida

def obter_movimentacoes():
    if supabase:
        try:
            res = supabase.table("movimentacoes_portaria").select("*").order("id", desc=True).execute()
            if res.data:
                return res.data
        except Exception:
            pass
    return st.session_state["movimentacoes_db"]

# --- CRIAÇÃO DAS ABAS ---
tab1, tab2, tab3 = st.tabs([
    "📝 1. Cadastro de Veículos", 
    "🚗 2. Controle de Portaria (Entrada/Saída)", 
    "📄 3. Relatórios / Exportação PDF"
])

OPCOES_POSTO = ["ADVOGADO(A)", "TEN CORONEL", "CORONEL", "OUTROS"]

# ==========================================
# ABA 1: CADASTRO DE VEÍCULOS
# ==========================================
with tab1:
    st.header("Cadastro de Veículos e Condutores Autorizados")
    
    val_placa_inicial = st.session_state.get("placa_prefill", "")
    
    with st.form("form_cadastro_veiculo", clear_on_submit=True):
        placa_cad = st.text_input("Placa do Veículo", value=val_placa_inicial, max_chars=8).upper()
        posto_cad = st.selectbox("Posto / Cargo", options=OPCOES_POSTO)
        nome_cad = st.text_input("Nome do Condutor / Autoridade")
        obs_cad = st.text_area("Observações")
        
        marcar_entrada_junto = st.checkbox("Registrar Entrada no Estacionamento Imediatamente", value=bool(val_placa_inicial))
        
        btn_salvar = st.form_submit_button("Salvar Cadastro", type="primary")
        
        if btn_salvar:
            if not placa_cad or not nome_cad:
                st.warning("Preencha a Placa e o Nome do Condutor.")
            else:
                salvar_veiculo(placa_cad, posto_cad, nome_cad, obs_cad)
                if marcar_entrada_junto:
                    registrar_entrada(placa_cad, posto_cad, nome_cad, obs_cad)
                    st.success(f"Veículo {placa_cad} cadastrado e ENTRADA registrada com sucesso!")
                else:
                    st.success(f"Veículo {placa_cad} cadastrado com sucesso!")
                st.session_state["placa_prefill"] = ""

# ==========================================
# ABA 2: CONTROLE DE PORTARIA
# ==========================================
with tab2:
    st.header("Controle de Entrada e Saída em Tempo Real")
    
    col_busca, col_vazio = st.columns([2, 1])
    
    with col_busca:
        placa_pesquisa = st.text_input("Digite a Placa do Veículo para Pesquisar/Registrar:", max_chars=8).strip().upper()
        
        if placa_pesquisa:
            dados_veiculo = buscar_veiculo(placa_pesquisa)
            
            if dados_veiculo:
                st.success("✅ Veículo Encontrado no Cadastro!")
                st.write(f"**Placa:** {dados_veiculo['placa']}")
                st.write(f"**Posto/Cargo:** {dados_veiculo['posto']}")
                st.write(f"**Nome:** {dados_veiculo['nome']}")
                st.write(f"**Obs:** {dados_veiculo.get('observacao', '')}")
                
                if st.button("🔴 Confirmar Entrada do Veículo", type="primary"):
                    registrar_entrada(
                        dados_veiculo['placa'], 
                        dados_veiculo['posto'], 
                        dados_veiculo['nome'], 
                        dados_veiculo.get('observacao', '')
                    )
                    st.success("Entrada registrada com sucesso!")
                    st.rerun()
            else:
                st.error("❌ Veículo NÃO CADASTRADO")
                if st.button("➕ Cadastrar Este Veículo Agora"):
                    st.session_state["placa_prefill"] = placa_pesquisa
                    st.info("Vá para a Aba '1. Cadastro de Veículos' para concluir o registro.")
    
    st.divider()
    st.subheader("📋 Veículos Registrados / Movimentação em Tempo Real")
    
    movimentacoes = obter_movimentacoes()
    
    if movimentacoes:
        for idx, mov in enumerate(reversed(movimentacoes)):
            c1, c2, c3, c4, c5, c6 = st.columns([1.5, 1.5, 2, 2, 2, 1.5])
            c1.write(f"**{mov['placa']}**")
            c2.write(mov['posto'])
            c3.write(mov['nome'])
            c4.write(f"Entrada: {mov['hora_entrada']}")
            c5.write(f"Saída: {mov['hora_saida']}")
            
            if mov['hora_saida'] == "Em Patio":
                if c6.button("🔴 Saída", key=f"saida_{idx}"):
                    registrar_saida(mov.get("id"), mov['placa'], mov['hora_entrada'])
                    st.rerun()
            else:
                c6.write("✅ Concluído")
            st.divider()
    else:
        st.info("Nenhuma movimentação registrada até o momento.")

# ==========================================
# ABA 3: RELATÓRIOS E EXPORTAÇÃO PDF
# ==========================================
with tab3:
    st.header("Relatório de Movimentação de Veículos")
    
    movs = obter_movimentacoes()
    
    if movs:
        df = pd.DataFrame(movs)
        cols_exibir = ["placa", "posto", "nome", "hora_entrada", "hora_saida", "observacao"]
        df_exibir = df[[c for c in cols_exibir if c in df.columns]]
        
        st.dataframe(df_exibir, use_container_width=True)
        
        def gerar_pdf(dados_movimentacao):
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
            elements = []
            
            styles = getSampleStyleSheet()
            titulo_style = ParagraphStyle(
                'Titulo',
                parent=styles['Heading1'],
                fontSize=14,
                alignment=1,
                spaceAfter=15
            )
            
            elements.append(Paragraph("<b>POLÍCIA MILITAR DE PERNAMBUCO</b>", titulo_style))
            elements.append(Paragraph("<b>QUARTEL COMANDO GERAL - RELATÓRIO DE PORTARIA</b>", titulo_style))
            elements.append(Spacer(1, 10))
            
            data_tabela = [["Placa", "Posto/Cargo", "Nome", "Entrada", "Saída", "Obs"]]
            for m in dados_movimentacao:
                data_tabela.append([
                    m.get("placa", ""),
                    m.get("posto", ""),
                    m.get("nome", ""),
                    m.get("hora_entrada", ""),
                    m.get("hora_saida", ""),
                    m.get("observacao", "")
                ])
                
            tabela = Table(data_tabela, colWidths=[60, 75, 105, 105, 105, 100])
            tabela.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            
            elements.append(tabela)
            doc.build(elements)
            buffer.seek(0)
            return buffer

        pdf_bytes = gerar_pdf(movs)
        
        st.download_button(
            label="📥 Baixar Relatório em PDF",
            data=pdf_bytes,
            file_name=f"relatorio_portaria_qcg_{datetime.date.today()}.pdf",
            mime="application/pdf",
            type="primary"
        )
    else:
        st.info("Não há dados registrados para gerar o relatório em PDF.")
