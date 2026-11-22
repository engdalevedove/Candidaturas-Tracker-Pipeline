import re
import sqlite3
import time
import unicodedata
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Job Hunt BI — Candidaturas",
    page_icon="📊",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "exports" / "candidaturas_bi.csv"
DB_PATH = BASE_DIR / "data" / "applications.db"

OPCOES_STATUS = [
    "Em Andamento",
    "Avançou de Etapa",
    "Não Avançou",
    "Contratado / Aprovado",
    "Vaga Cancelada",
]


def _normalizar_texto_corrompido(valor: str) -> str:
    s = str(valor or "").strip()
    if not s:
        return "Não Informado"
    if re.search(r"automa\?+o", s, flags=re.I):
        return "TI / Automação"
    if re.search(r"opera[cç][oõ\?]+es", s, flags=re.I):
        return "Comercial / Operações"
    if re.search(r"transforma[cç][oõ\?]+o", s, flags=re.I):
        return "Engenharia / Processos"
    if re.search(r"produ[cç][aã\?]+o", s, flags=re.I):
        return "Engenharia / Processos"
    return s


def _chave_comparacao(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (s or "").lower())
    sem_acento = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sem_acento).strip()


def _classificar_modalidade(cargo: str, obs: str, empresa: str) -> str:
    txt_principal = _chave_comparacao(f"{cargo} {obs}")
    txt_completo = _chave_comparacao(f"{cargo} {obs} {empresa}")

    if re.search(r"\b(remoto|remote|home office|100%\s*remoto|anywhere)\b", txt_completo):
        return "Remoto"
    if re.search(r"\b(hibrido|hybrid)\b", txt_completo):
        return "Híbrido"
    if re.search(r"\b(presencial|on-site|onsite)\b", txt_completo):
        return "Presencial"

    if re.search(
        r"\b(sao paulo|sp|bauru|marilia|campinas|curitiba|belo horizonte|rio de janeiro|jacarei|sao jose dos pinhais|luis eduardo magalhaes|barreiras)\b",
        txt_principal,
    ):
        return "Presencial"

    return "Não Informado"


def _reexportar_csv_apos_update(df_atualizado: pd.DataFrame) -> None:
    try:
        from src.database import exportar_para_bi  # type: ignore

        try:
            exportar_para_bi(str(CSV_PATH))
            return
        except TypeError:
            exportar_para_bi()
            return
    except Exception:
        pass

    cols_csv = [
        c
        for c in [
            "empresa",
            "cargo",
            "area",
            "plataforma",
            "data_inscricao",
            "data_retorno",
            "status",
            "obs",
        ]
        if c in df_atualizado.columns
    ]
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_atualizado[cols_csv].to_csv(CSV_PATH, index=False, encoding="utf-8-sig")


def _salvar_status_no_sqlite(
    empresa: str,
    cargo: str,
    data_inscricao: str,
    novo_status: str,
    data_retorno_str: str,
    nova_obs: str,
) -> tuple[bool, str]:
    if not DB_PATH.exists():
        return False, f"Banco não encontrado em `{DB_PATH}`."

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                """
                UPDATE candidaturas
                   SET status = ?,
                       data_retorno = ?,
                       obs = ?
                 WHERE empresa = ?
                   AND cargo = ?
                   AND COALESCE(data_inscricao, '') = COALESCE(?, '')
                """,
                (novo_status, data_retorno_str, nova_obs, empresa, cargo, data_inscricao),
            )
            if cur.rowcount == 0:
                cur = conn.execute(
                    """
                    UPDATE candidaturas
                       SET status = ?,
                           data_retorno = ?,
                           obs = ?
                     WHERE empresa = ?
                       AND cargo = ?
                    """,
                    (novo_status, data_retorno_str, nova_obs, empresa, cargo),
                )
            conn.commit()
            if cur.rowcount == 0:
                return False, "Nenhum registro correspondente encontrado no SQLite."

            df_db = pd.read_sql_query("SELECT * FROM candidaturas", conn)
        _reexportar_csv_apos_update(df_db)
        return True, f"Atualizado no SQLite e sincronizado no CSV ({cur.rowcount} linha(s))."
    except Exception as exc:
        return False, f"Erro ao atualizar SQLite: {exc}"


@st.cache_data(ttl=15)
def carregar_dados(csv_file: Path, mtime: float) -> pd.DataFrame:
    if not csv_file.exists():
        return pd.DataFrame()

    df = pd.read_csv(csv_file, encoding="utf-8-sig")
    if df.empty:
        return df

    for col in ["empresa", "cargo", "area", "plataforma", "status", "data_inscricao", "data_retorno", "obs"]:
        if col not in df.columns:
            df[col] = ""

    df["empresa"] = df["empresa"].fillna("").astype(str).str.strip()
    df["cargo"] = df["cargo"].fillna("").astype(str).str.strip()
    df["plataforma"] = df["plataforma"].fillna("Não Informada").astype(str).str.strip()
    df["area"] = df["area"].apply(_normalizar_texto_corrompido)
    df["status"] = df["status"].fillna("Em Andamento").astype(str).str.strip()
    df["data_inscricao"] = df["data_inscricao"].fillna("").astype(str).str.strip()
    df["data_retorno"] = df["data_retorno"].fillna("").astype(str).str.strip()
    df["obs"] = df["obs"].fillna("").astype(str).str.strip()

    df["modalidade"] = df.apply(
        lambda r: _classificar_modalidade(r["cargo"], r["obs"], r["empresa"]),
        axis=1,
    )

    df["dt_inscricao"] = pd.to_datetime(df["data_inscricao"], errors="coerce")
    df["dt_retorno"] = pd.to_datetime(df["data_retorno"], errors="coerce")

    df["status_chave"] = df["status"].apply(_chave_comparacao)
    df["teve_retorno"] = df["dt_retorno"].notna() | (df["status_chave"] != "em andamento")

    df["status_exibicao"] = df.apply(
        lambda r: r["status"]
        if r["status_chave"] != "em andamento"
        else ("Com Retorno (Aguardando Atualização)" if r["teve_retorno"] else "Em Andamento"),
        axis=1,
    )
    return df


def main() -> None:
    st.title("📊 Job Hunt BI — Painel de Candidaturas")
    st.caption(f"Fonte consolidada: `{CSV_PATH.relative_to(BASE_DIR)}`")

    # Barra lateral — Controles de atualização e filtros
    st.sidebar.header("Atualização & Filtros")

    if st.sidebar.button("🔄 Atualizar dados agora", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    auto_refresh = st.sidebar.checkbox("Auto-atualizar enquanto aberto", value=False)
    intervalo_seg = st.sidebar.slider("Intervalo (segundos)", min_value=5, max_value=60, value=15, step=5)

    mtime = CSV_PATH.stat().st_mtime if CSV_PATH.exists() else 0.0
    df = carregar_dados(CSV_PATH, mtime)
    if df.empty:
        st.warning("Arquivo `exports/candidaturas_bi.csv` não encontrado ou vazio. Execute `python main.py` primeiro.")
        return

    plataformas_sel = st.sidebar.multiselect(
        "Plataforma",
        options=sorted(df["plataforma"].unique()),
        default=sorted(df["plataforma"].unique()),
    )
    areas_sel = st.sidebar.multiselect(
        "Área",
        options=sorted(df["area"].unique()),
        default=sorted(df["area"].unique()),
    )
    modalidades_sel = st.sidebar.multiselect(
        "Modalidade",
        options=sorted(df["modalidade"].unique()),
        default=sorted(df["modalidade"].unique()),
    )
    status_sel = st.sidebar.multiselect(
        "Status de Acompanhamento",
        options=sorted(df["status_exibicao"].unique()),
        default=sorted(df["status_exibicao"].unique()),
    )
    somente_retorno = st.sidebar.checkbox("Apenas com retorno registrado", value=False)
    busca = st.sidebar.text_input("Buscar empresa ou cargo", placeholder="Ex.: Lanlink, Accenture, Dados...").strip()

    filtrado = df[
        df["plataforma"].isin(plataformas_sel)
        & df["area"].isin(areas_sel)
        & df["modalidade"].isin(modalidades_sel)
        & df["status_exibicao"].isin(status_sel)
    ].copy()

    if somente_retorno:
        filtrado = filtrado[filtrado["teve_retorno"]]

    if busca:
        b_norm = _chave_comparacao(busca)
        mascara = filtrado.apply(
            lambda r: b_norm in _chave_comparacao(r["empresa"])
            or b_norm in _chave_comparacao(r["cargo"])
            or b_norm in _chave_comparacao(r["obs"])
            or b_norm in _chave_comparacao(r["modalidade"]),
            axis=1,
        )
        filtrado = filtrado[mascara]

    # KPIs principais (contagem exata por status)
    total = len(filtrado)
    em_andamento_puro = int((~filtrado["teve_retorno"]).sum())
    com_retorno = int(filtrado["teve_retorno"].sum())
    avancou = int((filtrado["status_chave"] == "avancou de etapa").sum())
    nao_avancou = int((filtrado["status_chave"] == "nao avancou").sum())
    taxa_retorno = (com_retorno / total * 100) if total else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total de Candidaturas", f"{total}")
    c2.metric("Com Retorno Registrado", f"{com_retorno}", f"{taxa_retorno:.1f}% do total")
    c3.metric("Em Andamento (Sem Retorno)", f"{em_andamento_puro}")
    c4.metric("Avançou de Etapa", f"{avancou}")
    c5.metric("Não Avançou", f"{nao_avancou}")

    # Resumo por modalidade (Remota x Presencial x Híbrida x Não Informada)
    qtd_remoto = int((filtrado["modalidade"] == "Remoto").sum())
    qtd_presencial = int((filtrado["modalidade"] == "Presencial").sum())
    qtd_hibrido = int((filtrado["modalidade"] == "Híbrido").sum())
    qtd_nao_inf = int((filtrado["modalidade"] == "Não Informado").sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Remotas", f"{qtd_remoto}")
    m2.metric("Presenciais", f"{qtd_presencial}")
    m3.metric("Híbridas", f"{qtd_hibrido}")
    m4.metric("Modalidade Não Informada", f"{qtd_nao_inf}")

    st.divider()

    # Gráficos — Plataforma, Área e Modalidade
    col_esq, col_meio, col_dir = st.columns(3)

    with col_esq:
        st.subheader("Por Plataforma")
        por_plat = filtrado["plataforma"].value_counts().rename_axis("Plataforma").to_frame("Quantidade")
        st.bar_chart(por_plat)

    with col_meio:
        st.subheader("Por Área")
        por_area = filtrado["area"].value_counts().rename_axis("Área").to_frame("Quantidade")
        st.bar_chart(por_area)

    with col_dir:
        st.subheader("Por Modalidade")
        por_mod = filtrado["modalidade"].value_counts().rename_axis("Modalidade").to_frame("Quantidade")
        st.bar_chart(por_mod)

    # Evolução por data de inscrição
    st.subheader("Evolução de Inscrições por Data")
    df_datas = filtrado.dropna(subset=["dt_inscricao"]).copy()
    if not df_datas.empty:
        serie_datas = (
            df_datas.groupby(df_datas["dt_inscricao"].dt.date)
            .size()
            .rename_axis("Data de Inscrição")
            .to_frame("Candidaturas")
        )
        st.line_chart(serie_datas)
    else:
        st.info("Sem datas válidas em `data_inscricao` para o filtro selecionado.")

    # Atualização rápida de status direto no SQLite + exportação CSV
    with st.expander("✏️ Atualizar Status ou Retorno de uma Candidatura no Banco"):
        if not df.empty:
            opcoes_idx = [
                f"{r['empresa']} — {r['cargo']} ({r['plataforma']} | {r['data_inscricao'] or 'sem data'})"
                for _, r in df.sort_values(by=["empresa", "cargo"]).iterrows()
            ]
            mapa_opcoes = dict(
                zip(
                    opcoes_idx,
                    df.sort_values(by=["empresa", "cargo"]).to_dict("records"),
                )
            )
            escolha = st.selectbox("Selecione a candidatura", options=opcoes_idx)
            reg_sel = mapa_opcoes[escolha]

            status_atual_idx = 0
            for i, st_opt in enumerate(OPCOES_STATUS):
                if _chave_comparacao(st_opt) == _chave_comparacao(reg_sel["status"]):
                    status_atual_idx = i
                    break

            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                novo_status = st.selectbox("Novo Status", options=OPCOES_STATUS, index=status_atual_idx)
            with col_s2:
                dt_padrao = date.today()
                if reg_sel["data_retorno"]:
                    parsed = pd.to_datetime(reg_sel["data_retorno"], errors="coerce")
                    if pd.notna(parsed):
                        dt_padrao = parsed.date()
                preencher_retorno = st.checkbox("Registrar / manter data de retorno", value=bool(reg_sel["data_retorno"]) or novo_status != "Em Andamento")
                nova_dt_retorno = st.date_input("Data de Retorno", value=dt_padrao, disabled=not preencher_retorno)
            with col_s3:
                nova_obs = st.text_input("Observação", value=reg_sel["obs"])

            if st.button("💾 Salvar alteração no SQLite e CSV"):
                dt_ret_final = nova_dt_retorno.strftime("%Y-%m-%d") if preencher_retorno else ""
                ok, msg = _salvar_status_no_sqlite(
                    empresa=reg_sel["empresa"],
                    cargo=reg_sel["cargo"],
                    data_inscricao=reg_sel["data_inscricao"],
                    novo_status=novo_status,
                    data_retorno_str=dt_ret_final,
                    nova_obs=nova_obs,
                )
                if ok:
                    st.success(msg)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(msg)

    # Tabela detalhada com identificação explícita de Remota / Presencial
    st.subheader("Detalhamento das Candidaturas (Remotas e Presenciais)")
    colunas_exibir = [
        "data_inscricao",
        "empresa",
        "cargo",
        "modalidade",
        "area",
        "plataforma",
        "status_exibicao",
        "data_retorno",
        "obs",
    ]
    df_tab = filtrado.sort_values(by=["dt_inscricao", "empresa"], ascending=[False, True], na_position="last")[
        colunas_exibir
    ].rename(
        columns={
            "data_inscricao": "Data Inscrição",
            "empresa": "Empresa",
            "cargo": "Cargo",
            "modalidade": "Modalidade",
            "area": "Área",
            "plataforma": "Plataforma",
            "status_exibicao": "Status",
            "data_retorno": "Data Retorno",
            "obs": "Observações",
        }
    )
    st.dataframe(df_tab, use_container_width=True, hide_index=True)

    if auto_refresh:
        time.sleep(intervalo_seg)
        st.rerun()


if __name__ == "__main__":
    main()