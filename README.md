# chwcds.github.io

Site GitHub Pages pessoal.

## Vigia Edital Centec (`/vigia-centec`)

Monitor automático que verifica diariamente (07h de Brasília) se a Funec
(Fundação de Ensino de Contagem/MG) publicou novo edital de processo seletivo
de **estudantes** para cursos técnicos **subsequentes (pós-médio)** na unidade
**Centec** — Análises Clínicas, Farmácia e/ou Química — com ingresso a partir
de 2026/2 ou 2027.

- **Página:** https://chwcds.github.io/vigia-centec/
- **Script:** [`scripts/verificar_edital.py`](scripts/verificar_edital.py) —
  raspa o [portal de editais de Contagem](https://portal.contagem.mg.gov.br/portal/editais/3)
  e o site Estuda Contagem, aplica filtros de inclusão/exclusão e grava
  [`vigia-centec/status.json`](vigia-centec/status.json).
- **Workflow:** [`.github/workflows/vigia-centec.yml`](.github/workflows/vigia-centec.yml) —
  cron diário às 10:00 UTC + gatilho manual (`workflow_dispatch`). Commita o
  `status.json` só quando o conteúdo muda; se o status virar `PUBLICADO`,
  abre uma issue de alerta (gera notificação por e-mail).

### Rodar localmente

```bash
pip install requests beautifulsoup4
python scripts/verificar_edital.py
```
