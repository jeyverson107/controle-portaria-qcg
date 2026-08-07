import streamlit as st
from supabase import create_client, Client
from datetime import datetime
import pytz
import pandas as pd
from io import BytesIO

# Importações para geração de PDF
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# -------------------------------------------------------------
# 1. CONFIGURAÇÃO DE FUSO HORÁRIO (BRASÍLIA / RECIFE)
# -------------------------------------------------------------
FUSO_BR = pytz.timezone('America/Recife')

def obter_data_hora_atual():
    return datetime.now(FUSO_BR).strftime('%d/%m/%Y %H:%M:%S')

def obter_data_atual():
    return datetime.now(FUSO_BR).strftime('%Y-%m-%d')

def formatar_placa(placa_raw: str) -> str:
    if not placa_raw:
        return ""
    return placa_raw.strip().upper().replace("-", "").replace(" ", "")

# -------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA STREAMLIT
# -------------------------------------------------------------
st.set_page_config(
    page_title="Controle de Acesso - Portaria QCG",
    page_icon="🛡️",
    layout="wide"
)

# -------------------------------------------------------------
# CONEXÃO SUPABASE
# -------------------------------------------------------------
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# -------------------------------------------------------------
# AUTENTICAÇÃO E LOGIN
# -------------------------------------------------------------
USUARIOS = {
    "sentinela": "qcg2026",
    "admin": "coronel2026"
}

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🛡️ Controle de Acesso - Portaria QCG")
    st.subheader("Acesso ao Sistema")
    
    col_login, _ = st.columns([1, 2])
    with col_login:
        usuario_input = st.text_input("Usuário")
        senha_input = st.text_input("Senha", type="password")
        
        if st.button("Entrar", type="primary"):
            if usuario_input in USUARIOS and USUARIOS[usuario_input] == senha_input:
                st.session_state.logged_in = True
                st.session_state.usuario = usuario_input
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")
    st.stop()

# -------------------------------------------------------------
# LISTA EXCLUSIVA DE POSTOS AUTORIZADOS
# -------------------------------------------------------------
POSTOS_GRADUACOES = [
    "CORONEL",
    "TEN CORONEL",
    "ADVOGADO (A)",
    "CIVIS AUTORIZADOS",
    "PRESTADORES DE SERVIÇO",
    "OUTROS"
]

if "abrir_cadastro_rapido" not in st.session_state:
    st.session_state.abrir_cadastro_rapido = False

# Cabeçalho Principal
st.title("🛡️ Controle de Acesso - Portaria QCG")
st.caption(f"Usuário ativo: **{st.session_state.usuario}** | Data/Hora Oficial (BRT): **{obter_data_hora_atual()}**")

# Abas Principais
aba1, aba2, aba3, aba4 = st.tabs([
    "📋 Aba 1: Cadastro de Veículos",
    "🚗 Aba 2: Registro de Entrada",
    "🚘 Aba 3: Acompanhamento (Pátio Interno)",
    "📊 Aba 4: Histórico / Relatórios"
])

# -------------------------------------------------------------
# ABA 1: CADASTRO DE VEÍCULOS
# -------------------------------------------------------------
with aba1:
    st.header("📋 Cadastro de Veículos Autorizados")

    with st.form("form_cadastro_veiculo"):
        c1, c2 = st.columns([1, 2])
        with c1:
            placa_input = st.text_input("Placa do Veículo", help="Formatada automaticamente (ex: ABC1234)").strip()
            posto_input = st.selectbox("Posto / Cargo (Apenas Autorizados)", POSTOS_GRADUACOES)
        with c2:
            nome_input = st.text_input("Nome Completo do Condutor")
            obs_input = st.text_area("Observações (Setor, Telefone, Autorização, etc.)", height=68)
            
        c_btn1, c_btn2 = st.columns([1, 1])
        with c_btn1:
            btn_salvar = st.form_submit_button("💾 Salvar Cadastro", type="primary")
        with c_btn2:
            btn_salvar_e_entrar = st.form_submit_button("🟢 Salvar e Registrar Entrada Imediata")

        if btn_salvar or btn_salvar_e_entrar:
            placa_fmt = formatar_placa(placa_input)
            if not placa_fmt or not nome_input:
                st.error("Por favor, preencha pelo menos a Placa e o Nome Completo.")
            else:
                existe = supabase.table("cadastros").select("id").eq("placa", placa_fmt).execute()
                if existe.data:
                    supabase.table("cadastros").update({
                        "nome": nome_input,
                        "posto_cargo": posto_input,
                        "obs": obs_input
                    }).eq("placa", placa_fmt).execute()
                    st.success(f"Cadastro da placa {placa_fmt} atualizado com sucesso!")
                else:
                    supabase.table("cadastros").insert({
                        "placa": placa_fmt,
                        "nome": nome_input,
                        "posto_cargo": posto_input,
                        "obs": obs_input
                    }).execute()
                    st.success(f"Veículo com placa {placa_fmt} cadastrado com sucesso!")
                
                if btn_salvar_e_entrar:
                    em_patios = supabase.table("movimentacoes").select("id").eq("placa", placa_fmt).eq("status", "Em Trânsito").execute()
                    if em_patios.data:
                        st.warning(f"Veículo {placa_fmt} cadastrado, mas já se encontra no pátio do QCG!")
                    else:
                        hora_agora = obter_data_hora_atual()
                        supabase.table("movimentacoes").insert({
                            "placa": placa_fmt,
                            "nome": nome_input,
                            "posto_cargo": posto_input,
                            "hora_entrada": hora_agora,
                            "status": "Em Trânsito"
                        }).execute()
                        st.balloons()
                        st.success(f"Entrada registrada para {placa_fmt} às {hora_agora}!")
                st.rerun()

    st.divider()
    st.subheader("🔍 Consultar e Gerenciar Cadastros Existentes")
    
    busca_cad = st.text_input("Buscar Cadastro (digite placa ou parte do nome):").strip()
    
    if busca_cad:
        res_busca = supabase.table("cadastros").select("*").or_(f"placa.ilike.%{busca_cad}%,nome.ilike.%{busca_cad}%").execute()
    else:
        res_busca = supabase.table("cadastros").select("*").order("created_at", desc=True).limit(20).execute()
        
    if res_busca.data:
        df_cad = pd.DataFrame(res_busca.data)
        cols_exibicao = ["placa", "posto_cargo", "nome", "obs"]
        cols_existentes = [c for c in cols_exibicao if c in df_cad.columns]
        
        st.dataframe(df_cad[cols_existentes], use_container_width=True)
        
        with st.expander("🗑️ Opção de Exclusão de Cadastro"):
            placa_deletar = st.selectbox("Selecione a placa para excluir do cadastro:", [""] + list(df_cad["placa"].unique()))
            if placa_deletar:
                if st.button(f"Confirmar Exclusão de {placa_deletar}", type="secondary"):
                    supabase.table("cadastros").delete().eq("placa", placa_deletar).execute()
                    st.success(f"Cadastro {placa_deletar} excluído com sucesso!")
                    st.rerun()
    else:
        st.info("Nenhum cadastro encontrado.")


# -------------------------------------------------------------
# ABA 2: REGISTRO DE ENTRADA (COM CADASTRO RÁPIDO EMBUTIDO)
# -------------------------------------------------------------
with aba2:
    st.header("🚗 Registro de Entrada de Veículo")
    
    placa_digitada = st.text_input("Digite a Placa do Veículo:").strip()
    placa_fmt_entrada = formatar_placa(placa_digitada)
    
    if placa_fmt_entrada:
        st.markdown(f"**Placa Formatada:** `{placa_fmt_entrada}`")
        
        res_patio = supabase.table("movimentacoes").select("*").eq("placa", placa_fmt_entrada).eq("status", "Em Trânsito").execute()
        
        if res_patio.data:
            mov_aberta = res_patio.data[0]
            st.error(f"⚠️ **ATENÇÃO: Veículo já se encontra no interior do QCG!**")
            st.warning(f"Entrada registrada em: **{mov_aberta.get('hora_entrada')}** por **{mov_aberta.get('nome')}** ({mov_aberta.get('posto_cargo')})")
            st.info("Para dar saída neste veículo, acesse a **Aba 3: Acompanhamento (Pátio Interno)**.")
        else:
            res_cad = supabase.table("cadastros").select("*").eq("placa", placa_fmt_entrada).execute()
            
            if res_cad.data:
                cad = res_cad.data[0]
                st.success("✅ Veículo Encontrado no Cadastro de Autorizados!")
                
                col_i1, col_i2 = st.columns(2)
                with col_i1:
                    st.write(f"**Placa:** {cad.get('placa')}")
                    st.write(f"**Posto/Cargo:** {cad.get('posto_cargo')}")
                with col_i2:
                    st.write(f"**Nome:** {cad.get('nome')}")
                    st.write(f"**Observações:** {cad.get('obs', 'Nenhuma')}")
                    
                if st.button("🟢 Confirmar e Registrar Entrada", type="primary", use_container_width=True):
                    hora_entrada = obter_data_hora_atual()
                    supabase.table("movimentacoes").insert({
                        "placa": cad.get("placa"),
                        "nome": cad.get("nome"),
                        "posto_cargo": cad.get("posto_cargo"),
                        "hora_entrada": hora_entrada,
                        "status": "Em Trânsito"
                    }).execute()
                    st.success(f"Entrada de {cad.get('placa')} confirmada às {hora_entrada}!")
                    st.rerun()
            else:
                st.warning("⚠️ Veículo Não Cadastrado no Sistema!")
                
                # Exibe Formulário Rápido de Cadastro e Entrada na própria tela
                st.subheader(f"📝 Preencher Cadastro Rápido para {placa_fmt_entrada}")
                with st.form("form_cadastro_rapido_entrada"):
                    col_r1, col_r2 = st.columns([1, 2])
                    with col_r1:
                        posto_rapido = st.selectbox("Posto / Cargo", POSTOS_GRADUACOES)
                    with col_r2:
                        nome_rapido = st.text_input("Nome Completo do Condutor")
                    
                    obs_rapido = st.text_input("Observação (opcional)")
                    btn_cad_e_entrar = st.form_submit_button("🟢 Salvar e Confirmar Entrada Agora", type="primary")
                    
                    if btn_cad_e_entrar:
                        if not nome_rapido:
                            st.error("Por favor, preencha o Nome Completo.")
                        else:
                            # 1. Salva no cadastro
                            supabase.table("cadastros").insert({
                                "placa": placa_fmt_entrada,
                                "nome": nome_rapido,
                                "posto_cargo": posto_rapido,
                                "obs": obs_rapido
                            }).execute()
                            
                            # 2. Registra a entrada
                            hora_entrada = obter_data_hora_atual()
                            supabase.table("movimentacoes").insert({
                                "placa": placa_fmt_entrada,
                                "nome": nome_rapido,
                                "posto_cargo": posto_rapido,
                                "hora_entrada": hora_entrada,
                                "status": "Em Trânsito"
                            }).execute()
                            
                            st.balloons()
                            st.success(f"Cadastro e Entrada do veículo {placa_fmt_entrada} realizados com sucesso!")
                            st.rerun()


# -------------------------------------------------------------
# ABA 3: ACOMPANHAMENTO (PÁTIO INTERNO)
# -------------------------------------------------------------
with aba3:
    st.header("🚘 Veículos no Pátio Interno do QCG")
    
    res_presentes = supabase.table("movimentacoes").select("*").eq("status", "Em Trânsito").order("created_at", desc=True).execute()
    qtd_presentes = len(res_presentes.data) if res_presentes.data else 0
    
    st.metric(label="📊 Veículos Estacionados no QCG Agora", value=f"{qtd_presentes} veículo(s)")
    st.divider()
    
    if res_presentes.data:
        df_presentes = pd.DataFrame(res_presentes.data)
        
        st.subheader("Lista de Veículos Estacionados")
        
        for idx, row in df_presentes.iterrows():
            with st.container():
                c_p1, c_p2, c_p3, c_p4, c_p5 = st.columns([1.5, 2, 2.5, 2.5, 2])
                c_p1.write(f"**{row.get('placa')}**")
                c_p2.write(f"{row.get('posto_cargo')}")
                c_p3.write(f"{row.get('nome')}")
                c_p4.write(f"⏱️ Entrada: {row.get('hora_entrada')}")
                
                with c_p5:
                    if st.button(f"🔴 Registrar Saída", key=f"btn_saida_{row.get('id')}"):
                        st.session_state[f"confirm_saida_{row.get('id')}"] = True
                        
                if st.session_state.get(f"confirm_saida_{row.get('id')}", False):
                    st.warning(f"Confirmar saída do veículo {row.get('placa')}?")
                    c_sim, c_nao = st.columns([1, 1])
                    if c_sim.button("Sim, Dar Saída", key=f"sim_{row.get('id')}", type="primary"):
                        hora_saida = obter_data_hora_atual()
                        supabase.table("movimentacoes").update({
                            "hora_saida": hora_saida,
                            "status": "Concluído"
                        }).eq("id", row.get("id")).execute()
                        st.session_state[f"confirm_saida_{row.get('id')}"] = False
                        st.success(f"Saída do veículo {row.get('placa')} registrada às {hora_saida}!")
                        st.rerun()
                    if c_nao.button("Cancelar", key=f"nao_{row.get('id')}"):
                        st.session_state[f"confirm_saida_{row.get('id')}"] = False
                        st.rerun()
            st.divider()
    else:
        st.info("Nenhum veículo estacionado no pátio interno neste momento.")


# -------------------------------------------------------------
# FUNÇÃO PARA GERAR RELATÓRIO OFICIAL EM PDF
# -------------------------------------------------------------
def gerar_relatorio_pdf(df_dados, usuario_emissao):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'HeaderTitle',
        parent=styles['Heading1'],
        fontSize=14,
        leading=16,
        alignment=1,
        textColor=colors.HexColor("#1A2B4C"),
        fontName="Helvetica-Bold"
    )
    
    subtitle_style = ParagraphStyle(
        'HeaderSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=colors.HexColor("#333333"),
        fontName="Helvetica"
    )
    
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        fontName="Helvetica"
    )
    
    cell_header_style = ParagraphStyle(
        'TableHeaderCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        fontName="Helvetica-Bold",
        textColor=colors.whitesmoke
    )

    story = []
    
    story.append(Paragraph("POLÍCIA MILITAR DE PERNAMBUCO", title_style))
    story.append(Paragraph("QUARTEL GENERAL DA POLÍCIA MILITAR - QCG", subtitle_style))
    story.append(Paragraph("RELATÓRIO OFICIAL DE CONTROLE DE ACESSO E MOVIMENTAÇÃO DE VEÍCULOS", ParagraphStyle('Sub', parent=subtitle_style, fontName="Helvetica-Bold", fontSize=11)))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A2B4C")))
    story.append(Spacer(1, 10))
    
    data_emissao = obter_data_hora_atual()
    info_text = f"<b>Data/Hora de Emissão:</b> {data_emissao} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Responsável/Sentinela:</b> {usuario_emissao} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Total de Registros:</b> {len(df_dados)}"
    story.append(Paragraph(info_text, ParagraphStyle('Info', parent=styles['Normal'], fontSize=9)))
    story.append(Spacer(1, 15))
    
    headers = ["Placa", "Posto / Cargo", "Nome do Condutor", "Hora Entrada", "Hora Saída", "Status"]
    table_data = [[Paragraph(h, cell_header_style) for h in headers]]
    
    for _, row in df_dados.iterrows():
        placa = str(row.get('placa', ''))
        posto = str(row.get('posto_cargo', ''))
        nome = str(row.get('nome', ''))
        h_ent = str(row.get('hora_entrada', '') or '-')
        h_sai = str(row.get('hora_saida', '') or 'Em Trânsito')
        status = str(row.get('status', ''))
        
        table_data.append([
            Paragraph(placa, cell_style),
            Paragraph(posto, cell_style),
            Paragraph(nome, cell_style),
            Paragraph(h_ent, cell_style),
            Paragraph(h_sai, cell_style),
            Paragraph(status, cell_style)
        ])
        
    tabela = Table(table_data, colWidths=[65, 95, 150, 95, 95, 55])
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A2B4C")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
    ]))
    
    story.append(tabela)
    story.append(Spacer(1, 30))
    
    story.append(Paragraph("____________________________________________________", ParagraphStyle('Line', parent=subtitle_style, alignment=1)))
    story.append(Paragraph(f"<b>Sentinela de Serviço: {usuario_emissao}</b>", ParagraphStyle('Sign', parent=subtitle_style, alignment=1)))
    story.append(Paragraph("Portaria Principal - QCG/PMPE", ParagraphStyle('SubSign', parent=subtitle_style, alignment=1, fontSize=8)))

    doc.build(story)
    buffer.seek(0)
    return buffer

# -------------------------------------------------------------
# ABA 4: HISTÓRICO / RELATÓRIOS EM PDF
# -------------------------------------------------------------
with aba4:
    st.header("📊 Histórico Geral e Emissão de Relatório PDF")
    
    st.subheader("🔍 Filtros de Pesquisa")
    f_col1, f_col2, f_col3 = st.columns(3)
    
    with f_col1:
        filtro_placa = st.text_input("Filtrar por Placa:").strip().upper()
    with f_col2:
        filtro_posto = st.selectbox("Filtrar por Posto/Graduação:", ["TODOS"] + POSTOS_GRADUACOES)
    with f_col3:
        filtro_status = st.selectbox("Status da Movimentação:", ["TODOS", "Em Trânsito", "Concluído"])
        
    query = supabase.table("movimentacoes").select("*").order("created_at", desc=True)
    
    if filtro_placa:
        query = query.ilike("placa", f"%{filtro_placa}%")
    if filtro_posto != "TODOS":
        query = query.eq("posto_cargo", filtro_posto)
    if filtro_status != "TODOS":
        query = query.eq("status", filtro_status)
        
    res_hist = query.execute()
    
    if res_hist.data:
        df_hist = pd.DataFrame(res_hist.data)
        colunas_desejadas = ["placa", "posto_cargo", "nome", "hora_entrada", "hora_saida", "status"]
        cols_f = [c for c in colunas_desejadas if c in df_hist.columns]
        
        st.subheader("📋 Resultados da Consulta")
        st.dataframe(df_hist[cols_f], use_container_width=True)
        
        st.divider()
        st.subheader("📄 Gerar e Baixar Relatório Oficial em PDF")
        
        pdf_buffer = gerar_relatorio_pdf(df_hist[cols_f], st.session_state.usuario)
        
        st.download_button(
            label="🔴 Baixar Relatório Oficial (PDF)",
            data=pdf_buffer,
            file_name=f"relatorio_portaria_qcg_{obter_data_atual()}.pdf",
            mime="application/pdf",
            type="primary"
        )
    else:
        st.info("Nenhum registro encontrado para os filtros selecionados.")
