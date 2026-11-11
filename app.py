import os
import re
import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timedelta
import pytz
import pandas as pd
from io import BytesIO
from xml.sax.saxutils import escape

# Importações para geração de PDF
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# -------------------------------------------------------------
# 1. FUSO HORÁRIO E REGRAS DO SERVIÇO (24h, das 07:00 às 07:00)
# -------------------------------------------------------------
FUSO_BR = pytz.timezone('America/Recife')
HORA_TROCA_SERVICO = 7  # o serviço começa e termina às 07:00
STATUS_PATIO = "Em Trânsito"
STATUS_CONCLUIDO = "Concluído"


def agora_br() -> datetime:
    return datetime.now(FUSO_BR)


def obter_data_hora_atual():
    return agora_br().strftime('%d/%m/%Y %H:%M:%S')


def obter_data_atual():
    return agora_br().strftime('%Y-%m-%d')


def inicio_do_servico(momento: datetime) -> datetime:
    """Retorna as 07:00 do serviço ao qual o momento pertence.
    Ex.: 10:00 de 29/10 -> 07:00 de 29/10 ; 03:00 de 30/10 -> 07:00 de 29/10."""
    momento = momento.astimezone(FUSO_BR)
    if momento.hour < HORA_TROCA_SERVICO:
        momento = momento - timedelta(days=1)
    return FUSO_BR.localize(datetime(momento.year, momento.month, momento.day, HORA_TROCA_SERVICO, 0, 0))


def fim_do_servico(momento: datetime) -> datetime:
    return inicio_do_servico(momento) + timedelta(days=1)


def converter_data_banco(valor):
    """Converte o created_at (texto ISO do Supabase) para horário de Recife."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(FUSO_BR)
    except ValueError:
        return None


def formatar_placa(placa_raw: str) -> str:
    if not placa_raw:
        return ""
    return re.sub(r"[^A-Z0-9]", "", placa_raw.strip().upper())


def limpar_busca(texto: str) -> str:
    # Remove caracteres que quebram o filtro de busca do Supabase
    return re.sub(r"[,()%*\\]", "", texto or "").strip()


def avisar(msg: str, tipo: str = "success"):
    """Guarda uma mensagem para aparecer depois do recarregamento da tela."""
    st.session_state.setdefault("avisos", []).append((tipo, msg))


def mostrar_avisos():
    for tipo, msg in st.session_state.pop("avisos", []):
        getattr(st, tipo)(msg)


# -------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA STREAMLIT
# -------------------------------------------------------------
st.set_page_config(
    page_title="Controle de Acesso - Portaria QCG",
    page_icon=os.path.join(os.path.dirname(os.path.abspath(__file__)), "icone.png"),
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
# As senhas ficam nos "Secrets" do Streamlit (não aparecem no GitHub):
#   [usuarios]
#   sentinela = "SENHA_DO_SENTINELA"
#   admin = "SENHA_DO_ADMIN"
# -------------------------------------------------------------
# Senhas antigas, usadas SOMENTE enquanto os Secrets não forem configurados.
# Depois de configurar os Secrets, este bloco pode ser apagado.
_USUARIOS_PROVISORIOS = {"sentinela": "qcg2026", "admin": "coronel2026"}


def carregar_usuarios():
    try:
        usuarios = st.secrets["usuarios"]
        return {str(k).strip().lower(): str(v).strip() for k, v in usuarios.items()}, True
    except Exception:
        return dict(_USUARIOS_PROVISORIOS), False


USUARIOS, SENHAS_NOS_SECRETS = carregar_usuarios()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🛡️ Controle de Acesso - Portaria QCG")
    st.subheader("Acesso ao Sistema")

    col_login, _ = st.columns([1, 2])
    with col_login:
        with st.form("form_login"):
            usuario_input = st.text_input("Usuário", autocomplete="username")
            senha_input = st.text_input("Senha", type="password", autocomplete="current-password")
            entrar = st.form_submit_button("Entrar", type="primary")

        if entrar:
            # Ignora espaços sobrando e maiúsculas no usuário (comum no teclado do celular)
            usuario_ok = (usuario_input or "").strip().lower()
            senha_ok = (senha_input or "").strip()
            if usuario_ok in USUARIOS and USUARIOS[usuario_ok] == senha_ok:
                st.session_state.logged_in = True
                st.session_state.usuario = usuario_ok
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

# -------------------------------------------------------------
# SAÍDA AUTOMÁTICA AO FIM DO SERVIÇO
# Todo veículo NÃO permanente que entrou num serviço recebe saída
# automática às 07:00 do dia seguinte, caso ninguém registre a saída.
# A função roda dentro do banco (fechar_servicos_vencidos).
# -------------------------------------------------------------
def fechar_servicos_vencidos(forcar: bool = False) -> int:
    ultima = st.session_state.get("ultima_verificacao_turno")
    if not forcar and ultima and (agora_br() - ultima).total_seconds() < 60:
        return 0
    st.session_state.ultima_verificacao_turno = agora_br()
    try:
        res = supabase.rpc("fechar_servicos_vencidos").execute()
        return int(res.data or 0)
    except Exception as e:
        st.warning(f"Não foi possível verificar as saídas automáticas agora: {e}")
        return 0


def servico_atual():
    inicio = inicio_do_servico(agora_br())
    res = supabase.table("servicos").select("*").eq("inicio", inicio.isoformat()).execute()
    return (res.data[0] if res.data else None), inicio


def registrar_entrada(placa, nome, posto, permanente=False, obs_permanencia=""):
    servico, _ = servico_atual()
    hora = obter_data_hora_atual()
    supabase.table("movimentacoes").insert({
        "placa": placa,
        "nome": nome,
        "posto_cargo": posto,
        "hora_entrada": hora,
        "status": STATUS_PATIO,
        "permanente": bool(permanente),
        "obs_permanencia": obs_permanencia or None,
        "servico_id": servico["id"] if servico else None,
        "usuario_entrada": st.session_state.usuario,
    }).execute()
    return hora


def obs_por_placa(placas) -> dict:
    """Busca as observações do cadastro (reserva, atividade, telefone etc.) de cada placa."""
    placas = sorted({p for p in placas if p})
    if not placas:
        return {}
    try:
        res = supabase.table("cadastros").select("placa,obs").in_("placa", placas).execute()
        return {r["placa"]: (r.get("obs") or "").strip() for r in (res.data or [])}
    except Exception:
        return {}


qtd_auto = fechar_servicos_vencidos()
if qtd_auto:
    avisar(f"🕖 {qtd_auto} veículo(s) do serviço anterior receberam saída automática (fim do serviço às 07:00).", "info")

if "abrir_cadastro_rapido" not in st.session_state:
    st.session_state.abrir_cadastro_rapido = False

# Cabeçalho Principal
cab1, cab2 = st.columns([5, 1])
with cab1:
    st.title("🛡️ Controle de Acesso - Portaria QCG")
    st.caption(f"Usuário ativo: **{st.session_state.usuario}** | Data/Hora Oficial (BRT): **{obter_data_hora_atual()}**")
with cab2:
    if st.button("🚪 Sair", width='stretch'):
        st.session_state.clear()
        st.rerun()

if not SENHAS_NOS_SECRETS and st.session_state.usuario == "admin":
    st.warning("⚠️ As senhas ainda estão no código público do GitHub. Configure-as nos *Secrets* do Streamlit.")

# -------------------------------------------------------------
# PAINEL DO SERVIÇO (07:00 -> 07:00)
# -------------------------------------------------------------
servico, inicio_serv = servico_atual()
fim_serv = inicio_serv + timedelta(days=1)
periodo_txt = f"{inicio_serv.strftime('%d/%m %H:%M')} até {fim_serv.strftime('%d/%m %H:%M')}"

if servico:
    sentinela_txt = servico.get("sentinela") or servico.get("usuario")
    iniciado = converter_data_banco(servico.get("iniciado_em"))
    st.success(
        f"🟢 **Serviço em andamento:** {periodo_txt} · Sentinela: **{sentinela_txt}**"
        + (f" · botão apertado às {iniciado.strftime('%H:%M')}" if iniciado else "")
    )
else:
    with st.container(border=True):
        st.warning(f"⏸️ **Serviço de {periodo_txt} ainda não foi iniciado no sistema.**")
        with st.form("form_iniciar_servico"):
            ci1, ci2 = st.columns([2, 3])
            sentinela_nome = ci1.text_input("Sentinela de serviço (posto/graduação e nome)")
            obs_servico = ci2.text_input("Observação (opcional)")
            st.caption("Não importa a hora em que o botão for apertado: o serviço sempre conta a partir das 07:00.")
            if st.form_submit_button("▶️ Iniciar Serviço", type="primary"):
                try:
                    supabase.table("servicos").insert({
                        "inicio": inicio_serv.isoformat(),
                        "fim": fim_serv.isoformat(),
                        "usuario": st.session_state.usuario,
                        "sentinela": sentinela_nome.strip() or st.session_state.usuario,
                        "observacao": obs_servico.strip() or None,
                    }).execute()
                    n = fechar_servicos_vencidos(forcar=True)
                    avisar(f"✅ Serviço iniciado ({periodo_txt})."
                           + (f" {n} veículo(s) do serviço anterior receberam saída automática." if n else ""))
                except Exception:
                    avisar("Este serviço já havia sido iniciado por outro usuário.", "info")
                st.rerun()

mostrar_avisos()

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

    with st.form("form_cadastro_veiculo", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            placa_input = st.text_input("Placa do Veículo", help="Formatada automaticamente (ex: ABC1234)").strip()
            posto_input = st.selectbox("Posto / Cargo (Apenas Autorizados)", POSTOS_GRADUACOES)
        with c2:
            nome_input = st.text_input("Nome Completo do Condutor")
            obs_input = st.text_area("Observações (Setor, Telefone, Autorização, etc.)", height=68)

        perm_cad = st.checkbox("📌 Ao registrar a entrada, marcar como estacionamento permanente (vai ficar mais de um serviço)")

        c_btn1, c_btn2 = st.columns([1, 1])
        with c_btn1:
            btn_salvar = st.form_submit_button("💾 Salvar Cadastro", type="primary")
        with c_btn2:
            btn_salvar_e_entrar = st.form_submit_button("🟢 Salvar e Registrar Entrada Imediata")

        if btn_salvar or btn_salvar_e_entrar:
            placa_fmt = formatar_placa(placa_input)
            nome_input = nome_input.strip()
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
                    avisar(f"Cadastro da placa {placa_fmt} atualizado com sucesso!")
                else:
                    supabase.table("cadastros").insert({
                        "placa": placa_fmt,
                        "nome": nome_input,
                        "posto_cargo": posto_input,
                        "obs": obs_input
                    }).execute()
                    avisar(f"Veículo com placa {placa_fmt} cadastrado com sucesso!")

                if btn_salvar_e_entrar:
                    em_patios = supabase.table("movimentacoes").select("id").eq("placa", placa_fmt).eq("status", STATUS_PATIO).execute()
                    if em_patios.data:
                        avisar(f"Veículo {placa_fmt} cadastrado, mas já se encontra no pátio do QCG!", "warning")
                    else:
                        hora_agora = registrar_entrada(placa_fmt, nome_input, posto_input, perm_cad)
                        avisar(f"Entrada registrada para {placa_fmt} às {hora_agora}!"
                               + (" (📌 permanente)" if perm_cad else ""))
                st.rerun()

    st.divider()
    st.subheader("🔍 Consultar e Gerenciar Cadastros Existentes")

    busca_cad = limpar_busca(st.text_input("Buscar Cadastro (digite placa ou parte do nome):"))

    if busca_cad:
        busca_placa = formatar_placa(busca_cad) or busca_cad
        res_busca = supabase.table("cadastros").select("*").or_(f"placa.ilike.%{busca_placa}%,nome.ilike.%{busca_cad}%").order("nome").execute()
    else:
        res_busca = supabase.table("cadastros").select("*").order("created_at", desc=True).limit(20).execute()
        st.caption("Mostrando os 20 cadastros mais recentes. Use a busca para encontrar os demais.")

    if res_busca.data:
        df_cad = pd.DataFrame(res_busca.data)
        cols_exibicao = ["placa", "posto_cargo", "nome", "obs"]
        cols_existentes = [c for c in cols_exibicao if c in df_cad.columns]

        st.dataframe(
            df_cad[cols_existentes].rename(columns={
                "placa": "Placa", "posto_cargo": "Posto/Cargo", "nome": "Nome", "obs": "Observações",
            }),
            width='stretch', hide_index=True,
        )

        # Ficha completa: mostra a observação inteira (telefone, reserva, atividade etc.)
        opcoes_ficha = [""] + [f"{r['placa']} — {r.get('nome') or ''}" for r in res_busca.data]
        ficha_sel = st.selectbox("📇 Ver ficha completa do veículo:", opcoes_ficha)
        if ficha_sel:
            placa_ficha = ficha_sel.split(" — ")[0]
            cad_ficha = next((r for r in res_busca.data if r["placa"] == placa_ficha), None)
            if cad_ficha:
                with st.container(border=True):
                    st.write(f"**Placa:** {cad_ficha.get('placa')}")
                    st.write(f"**Posto/Cargo:** {cad_ficha.get('posto_cargo')}")
                    st.write(f"**Nome:** {cad_ficha.get('nome')}")
                    st.write(f"**Observações:** {cad_ficha.get('obs') or 'Nenhuma'}")

        with st.expander("🗑️ Opção de Exclusão de Cadastro"):
            placa_deletar = st.selectbox("Selecione a placa para excluir do cadastro:", [""] + list(df_cad["placa"].unique()))
            if placa_deletar:
                if st.button(f"Confirmar Exclusão de {placa_deletar}", type="secondary"):
                    supabase.table("cadastros").delete().eq("placa", placa_deletar).execute()
                    avisar(f"Cadastro {placa_deletar} excluído com sucesso!")
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

        res_patio = supabase.table("movimentacoes").select("*").eq("placa", placa_fmt_entrada).eq("status", STATUS_PATIO).execute()

        if res_patio.data:
            mov_aberta = res_patio.data[0]
            st.error("⚠️ **ATENÇÃO: Veículo já se encontra no interior do QCG!**")
            st.warning(f"Entrada registrada em: **{mov_aberta.get('hora_entrada')}** por **{mov_aberta.get('nome')}** ({mov_aberta.get('posto_cargo')})")
            obs_aberta = obs_por_placa([placa_fmt_entrada]).get(placa_fmt_entrada)
            if obs_aberta:
                st.info(f"📝 **Observações:** {obs_aberta}")
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
                    st.write(f"**Observações:** {cad.get('obs') or 'Nenhuma'}")

                perm_ent = st.checkbox("📌 Estacionamento permanente (o veículo vai ficar mais de um serviço)", key="perm_ent")
                obs_perm = ""
                if perm_ent:
                    obs_perm = st.text_input("Motivo / previsão de saída (opcional)", key="obs_perm_ent")
                else:
                    st.caption(f"Se ninguém registrar a saída, ela será dada automaticamente às {fim_serv.strftime('%H:%M de %d/%m')}.")

                if st.button("🟢 Confirmar e Registrar Entrada", type="primary", width='stretch'):
                    hora_entrada = registrar_entrada(cad.get("placa"), cad.get("nome"), cad.get("posto_cargo"), perm_ent, obs_perm)
                    avisar(f"Entrada de {cad.get('placa')} confirmada às {hora_entrada}!" + (" (📌 permanente)" if perm_ent else ""))
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
                    perm_rapido = st.checkbox("📌 Estacionamento permanente (o veículo vai ficar mais de um serviço)")
                    btn_cad_e_entrar = st.form_submit_button("🟢 Salvar e Confirmar Entrada Agora", type="primary")

                    if btn_cad_e_entrar:
                        nome_rapido = nome_rapido.strip()
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
                            registrar_entrada(placa_fmt_entrada, nome_rapido, posto_rapido, perm_rapido)
                            avisar(f"Cadastro e Entrada do veículo {placa_fmt_entrada} realizados com sucesso!")
                            st.rerun()


# -------------------------------------------------------------
# ABA 3: ACOMPANHAMENTO (PÁTIO INTERNO)
# -------------------------------------------------------------
def linha_veiculo(row, obs_cadastro=""):
    mov_id = row.get("id")
    permanente = bool(row.get("permanente"))
    with st.container(border=True):
        c_p1, c_p2, c_p3, c_p4 = st.columns([1.5, 2, 3, 3])
        c_p1.write(f"**{row.get('placa')}**" + (" 📌" if permanente else ""))
        c_p2.write(f"{row.get('posto_cargo')}")
        c_p3.write(f"{row.get('nome')}")
        c_p4.write(f"⏱️ Entrada: {row.get('hora_entrada')}")
        if obs_cadastro:
            st.info(f"📝 **Observações:** {obs_cadastro}")

        if permanente:
            if row.get("obs_permanencia"):
                st.caption(f"📌 Permanente — {row.get('obs_permanencia')}")
        else:
            base = converter_data_banco(row.get("base_turno") or row.get("created_at"))
            if base:
                st.caption(f"🕖 Saída automática às {fim_do_servico(base).strftime('%H:%M de %d/%m')} se não for registrada antes.")

        b1, b2, _ = st.columns([2, 3, 3])
        if b1.button("🔴 Registrar Saída", key=f"btn_saida_{mov_id}"):
            st.session_state[f"confirm_saida_{mov_id}"] = True

        if permanente:
            if b2.button("↩️ Deixar de ser permanente", key=f"perm_off_{mov_id}",
                         help="O veículo passa a sair automaticamente ao fim do serviço atual."):
                supabase.table("movimentacoes").update({
                    "permanente": False,
                    "base_turno": agora_br().isoformat(),
                }).eq("id", mov_id).execute()
                avisar(f"{row.get('placa')} deixou de ser permanente e sairá às {fim_serv.strftime('%H:%M de %d/%m')} se não for retirado antes.")
                st.rerun()
        else:
            if b2.button("📌 Tornar permanente", key=f"perm_on_{mov_id}",
                         help="O veículo não recebe saída automática ao fim do serviço."):
                supabase.table("movimentacoes").update({"permanente": True}).eq("id", mov_id).execute()
                avisar(f"{row.get('placa')} marcado como estacionamento permanente.")
                st.rerun()

        if st.session_state.get(f"confirm_saida_{mov_id}", False):
            st.warning(f"Confirmar saída do veículo {row.get('placa')}?")
            c_sim, c_nao = st.columns([1, 1])
            if c_sim.button("Sim, Dar Saída", key=f"sim_{mov_id}", type="primary"):
                hora_saida = obter_data_hora_atual()
                supabase.table("movimentacoes").update({
                    "hora_saida": hora_saida,
                    "status": STATUS_CONCLUIDO,
                    "usuario_saida": st.session_state.usuario,
                }).eq("id", mov_id).execute()
                st.session_state[f"confirm_saida_{mov_id}"] = False
                avisar(f"Saída do veículo {row.get('placa')} registrada às {hora_saida}!")
                st.rerun()
            if c_nao.button("Cancelar", key=f"nao_{mov_id}"):
                st.session_state[f"confirm_saida_{mov_id}"] = False
                st.rerun()


with aba3:
    st.header("🚘 Veículos no Pátio Interno do QCG")

    res_presentes = supabase.table("movimentacoes").select("*").eq("status", STATUS_PATIO).order("created_at", desc=True).execute()
    presentes = res_presentes.data or []
    obs_patio = obs_por_placa(r.get("placa") for r in presentes)
    permanentes = [r for r in presentes if r.get("permanente")]
    do_servico = [r for r in presentes if not r.get("permanente")]

    m1, m2, m3 = st.columns(3)
    m1.metric("📊 Veículos no QCG agora", f"{len(presentes)}")
    m2.metric("🕖 Deste serviço", f"{len(do_servico)}")
    m3.metric("📌 Permanentes", f"{len(permanentes)}")

    busca_patio = formatar_placa(st.text_input("Filtrar pátio por placa:", key="busca_patio"))
    if busca_patio:
        do_servico = [r for r in do_servico if busca_patio in (r.get("placa") or "")]
        permanentes = [r for r in permanentes if busca_patio in (r.get("placa") or "")]

    st.divider()

    if not presentes:
        st.info("Nenhum veículo estacionado no pátio interno neste momento.")
    else:
        st.subheader(f"🕖 Veículos deste serviço ({len(do_servico)})")
        if do_servico:
            for row in do_servico:
                linha_veiculo(row, obs_patio.get(row.get("placa"), ""))
        else:
            st.caption("Nenhum.")

        st.subheader(f"📌 Estacionamento permanente ({len(permanentes)})")
        if permanentes:
            st.caption("Estes veículos NÃO recebem saída automática. Confira-os a cada serviço.")
            for row in permanentes:
                linha_veiculo(row, obs_patio.get(row.get("placa"), ""))
        else:
            st.caption("Nenhum.")


# -------------------------------------------------------------
# FUNÇÃO PARA GERAR RELATÓRIO OFICIAL EM PDF
# -------------------------------------------------------------
def gerar_relatorio_pdf(df_dados, usuario_emissao, periodo_descricao=""):
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
    story.append(Paragraph("QUARTEL DO COMANDO GERAL DA POLÍCIA MILITAR - QCG", subtitle_style))
    story.append(Paragraph("RELATÓRIO OFICIAL DE CONTROLE DE ACESSO E MOVIMENTAÇÃO DE VEÍCULOS", ParagraphStyle('Sub', parent=subtitle_style, fontName="Helvetica-Bold", fontSize=11)))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A2B4C")))
    story.append(Spacer(1, 10))

    data_emissao = obter_data_hora_atual()
    info_text = f"<b>Data/Hora de Emissão:</b> {data_emissao} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Responsável/Sentinela:</b> {usuario_emissao} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Total de Registros:</b> {len(df_dados)}"
    if periodo_descricao:
        info_text += f"<br/><b>Período:</b> {periodo_descricao}"
    story.append(Paragraph(info_text, ParagraphStyle('Info', parent=styles['Normal'], fontSize=9, leading=13)))
    story.append(Spacer(1, 15))

    headers = ["Placa", "Posto / Cargo", "Nome do Condutor", "Hora Entrada", "Hora Saída", "Situação", "Observações"]
    table_data = [[Paragraph(h, cell_header_style) for h in headers]]

    def txt(valor, padrao=''):
        # Evita "nan"/"None" no PDF quando o campo está vazio
        if valor is None or (isinstance(valor, float) and pd.isna(valor)) or str(valor).strip() == '':
            return padrao
        return escape(str(valor))

    for _, row in df_dados.iterrows():
        table_data.append([
            Paragraph(txt(row.get('placa')), cell_style),
            Paragraph(txt(row.get('posto_cargo')), cell_style),
            Paragraph(txt(row.get('nome')), cell_style),
            Paragraph(txt(row.get('hora_entrada'), '-'), cell_style),
            Paragraph(txt(row.get('hora_saida'), 'Em Trânsito'), cell_style),
            Paragraph(txt(row.get('situacao')) or txt(row.get('status')), cell_style),
            Paragraph(txt(row.get('obs')), cell_style)
        ])

    tabela = Table(table_data, colWidths=[52, 62, 105, 68, 68, 62, 118])
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


def descrever_situacao(row) -> str:
    if row.get("status") == STATUS_PATIO:
        return "No pátio (permanente)" if row.get("permanente") else "No pátio"
    if row.get("saida_automatica"):
        return "Saída automática (fim do serviço)"
    return "Saída registrada"


# -------------------------------------------------------------
# ABA 4: HISTÓRICO / RELATÓRIOS EM PDF
# -------------------------------------------------------------
with aba4:
    st.header("📊 Histórico Geral e Emissão de Relatório PDF")

    st.subheader("🔍 Filtros de Pesquisa")
    periodo = st.radio("Período:", ["Serviço atual", "Serviço de um dia", "Entre datas", "Todo o histórico"], horizontal=True)

    ini_filtro = fim_filtro = None
    descricao_periodo = "Todo o histórico"
    if periodo == "Serviço atual":
        ini_filtro, fim_filtro = inicio_serv, fim_serv
    elif periodo == "Serviço de um dia":
        dia = st.date_input("Dia em que o serviço começou (às 07:00):", value=inicio_serv.date(), format="DD/MM/YYYY")
        ini_filtro = FUSO_BR.localize(datetime(dia.year, dia.month, dia.day, HORA_TROCA_SERVICO))
        fim_filtro = ini_filtro + timedelta(days=1)
    elif periodo == "Entre datas":
        d1, d2 = st.columns(2)
        data_ini = d1.date_input("De:", value=(agora_br() - timedelta(days=7)).date(), format="DD/MM/YYYY")
        data_fim = d2.date_input("Até:", value=agora_br().date(), format="DD/MM/YYYY")
        ini_filtro = FUSO_BR.localize(datetime(data_ini.year, data_ini.month, data_ini.day))
        fim_filtro = FUSO_BR.localize(datetime(data_fim.year, data_fim.month, data_fim.day)) + timedelta(days=1)
    if ini_filtro:
        descricao_periodo = f"{ini_filtro.strftime('%d/%m/%Y %H:%M')} até {fim_filtro.strftime('%d/%m/%Y %H:%M')}"
        st.caption(f"Entradas registradas de **{descricao_periodo}**.")

    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        filtro_placa = formatar_placa(st.text_input("Filtrar por Placa:"))
    with f_col2:
        filtro_posto = st.selectbox("Filtrar por Posto/Graduação:", ["TODOS"] + POSTOS_GRADUACOES)
    with f_col3:
        filtro_status = st.selectbox("Situação:", ["TODOS", "No pátio", "Saída registrada", "Saída automática"])

    query = supabase.table("movimentacoes").select("*").order("created_at", desc=True)

    if ini_filtro:
        query = query.gte("created_at", ini_filtro.isoformat()).lt("created_at", fim_filtro.isoformat())
    if filtro_placa:
        query = query.ilike("placa", f"%{filtro_placa}%")
    if filtro_posto != "TODOS":
        query = query.eq("posto_cargo", filtro_posto)
    if filtro_status == "No pátio":
        query = query.eq("status", STATUS_PATIO)
    elif filtro_status == "Saída registrada":
        query = query.eq("status", STATUS_CONCLUIDO).eq("saida_automatica", False)
    elif filtro_status == "Saída automática":
        query = query.eq("saida_automatica", True)

    res_hist = query.execute()

    if res_hist.data:
        df_hist = pd.DataFrame(res_hist.data)
        df_hist["situacao"] = df_hist.apply(descrever_situacao, axis=1)
        obs_hist = obs_por_placa(df_hist["placa"].tolist())
        df_hist["obs"] = df_hist["placa"].map(lambda p: obs_hist.get(p, ""))
        colunas_desejadas = ["placa", "posto_cargo", "nome", "hora_entrada", "hora_saida", "situacao", "obs"]
        cols_f = [c for c in colunas_desejadas if c in df_hist.columns]

        st.subheader(f"📋 Resultados da Consulta ({len(df_hist)})")
        st.dataframe(
            df_hist[cols_f].rename(columns={
                "placa": "Placa", "posto_cargo": "Posto/Cargo", "nome": "Nome",
                "hora_entrada": "Entrada", "hora_saida": "Saída", "situacao": "Situação",
                "obs": "Observações",
            }),
            width='stretch', hide_index=True,
        )

        st.divider()
        st.subheader("📄 Gerar e Baixar Relatório Oficial em PDF")

        pdf_buffer = gerar_relatorio_pdf(df_hist[cols_f], st.session_state.usuario, descricao_periodo)

        st.download_button(
            label="🔴 Baixar Relatório Oficial (PDF)",
            data=pdf_buffer,
            file_name=f"relatorio_portaria_qcg_{obter_data_atual()}.pdf",
            mime="application/pdf",
            type="primary"
        )
    else:
        st.info("Nenhum registro encontrado para os filtros selecionados.")
