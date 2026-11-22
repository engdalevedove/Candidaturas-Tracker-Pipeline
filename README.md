# 📊 Candidaturas-Tracker-Pipeline (Job Hunt BI)

Pipeline end-to-end de Engenharia de Dados, Automação (RPA) e Business Intelligence desenvolvido para consolidar, deduplicar e monitorar candidaturas de emprego espalhadas por múltiplos portais ATS, redes profissionais e e-mails em uma única base analítica.

---

## 🎯 Problema Resolvido

Ao participar de dezenas de processos seletivos simultâneos em diferentes plataformas, o acompanhamento manual por planilhas torna-se lento e propenso a duplicidades ou perda de prazos. Este projeto automatiza toda a jornada: desde a captura autenticada nos portais até a persistência relacional, alertas em tempo real e visualização executiva.

---

## 🏗️ Arquitetura do Pipeline

```text
[Fontes & Portais]
 ├── APIs Diretas: Gupy, Sólides
 ├── Automação Web (Playwright): LinkedIn (/jobs-tracker/), Indeed, B2HR, Workday, Cornerstone
 └── E-mail (IMAP): Gmail, Hotmail (com isolamento de falhas por conta)
        │
        ▼
[Processamento & Padronização — Python + Pandas]
 ├── Limpeza de strings e normalização de codificação (UTF-8 / NFKD)
 ├── Classificação automática de Área (Dados/BI, TI/Automação, Engenharia/Processos)
 ├── Inferência de Modalidade (Remoto, Presencial, Híbrido)
 └── Deduplicação e Upsert transacional
        │
        ▼
[Persistência & Exportação]
 ├── SQLite (data/applications.db)
 └── Camada Analítica CSV (exports/candidaturas_bi.csv)
        │
        ├──► [Notificações] Telegram Bot API (alertas de novos registros e mudanças de etapa)
        └──► [Analytics / BI] Dashboard Interativo em Streamlit (dashboard.py) & Power BI