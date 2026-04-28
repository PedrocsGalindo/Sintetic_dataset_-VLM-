# synthetic_tables

`synthetic_tables` e um projeto Python modular para gerar datasets sinteticos de tabelas voltados a OCR, extracao de tabelas e avaliacao de sistemas VLM/document understanding.

O pipeline gera uma mesma tabela estruturada em varios artefatos: schema JSON, CSV, XLSX, fontes intermediarias em HTML/LaTeX/Markdown, PDFs renderizados, imagens PNG por pagina e metadados JSONL. A ideia e manter a rastreabilidade do conteudo tabular enquanto varia formato, estilo, layout e DPI de rasterizacao.

## Visao Geral

O fluxo principal esta em `synthetic_tables/src/main.py` e roda de ponta a ponta:

1. Gera schemas sinteticos com tipos de coluna coerentes.
2. Materializa linhas e valores a partir desses schemas.
3. Exporta a tabela base para CSV e XLSX.
4. Amostra um estilo deterministico por tabela, formato e versao visual.
5. Renderiza fontes intermediarias em HTML, LaTeX e/ou Markdown.
6. Converte cada fonte intermediaria para PDF.
7. Rasteriza cada PDF em imagens PNG no(s) DPI(s) configurado(s).
8. Registra metadados de tabelas em `tables.jsonl`.
9. Registra metadados de amostras visuais em `samples.jsonl`.

Formatos gerados:

- `json`: schemas das tabelas base.
- `csv`: tabela base simples.
- `xlsx`: tabela base em planilha.
- `html`: representacao intermediaria com templates Jinja.
- `tex`: representacao intermediaria LaTeX com templates Jinja.
- `md`: representacao intermediaria Markdown gerada programaticamente.
- `pdf`: PDF final por formato intermediario.
- `png`: imagens por pagina extraidas de cada PDF.
- `jsonl`: metadados de tabelas e amostras.

Renderers atuais:

- `HTMLRenderer`: gera HTML a partir de templates.
- `MarkdownRenderer`: gera Markdown programaticamente.
- `LatexRenderer`: gera LaTeX a partir de templates.
- `PDFRenderer`: converte HTML, Markdown e LaTeX para PDF.
- `PDFToImageConverter`: converte PDF em imagens PNG.

## Estrutura Atual Do Projeto

```text
.
  README.md
  requirements.txt
  synthetic_tables/
    data/
      base_tables/
        csv/
        xlsx/
        schemas/
      rendered/
        html/
        latex/
        markdown/
        pdf/
        images/
        diagnostics/
      metadata/
        tables.jsonl
        samples.jsonl
    src/
      config.py
      main.py
      latex_smoke_test.py
      generators/
        schema_generator.py
        column_generators.py
        table_generator.py
      exporters/
        csv_exporter.py
        xlsx_exporter.py
        format_exporter.py
      styles/
        style_sampler.py
        templates/
          html/
            simple_tabular.html.j2
            default_table.html.j2
            document_columns.html.j2
            document_stream.html.j2
            numeric_blocks.html.j2
            hybrid_mosaic.html.j2
            editorial_blocks.html.j2
            procedure_form.html.j2
          latex/
            simple_tabular.tex.j2
            default_table.tex.j2
            executive_brief.tex.j2
            editorial_report.tex.j2
            data_memo.tex.j2
            record_cards.tex.j2
            split_matrix.tex.j2
            _shared_*.tex.j2
      renderers/
        html_renderer.py
        markdown_renderer.py
        latex_renderer.py
        pdf_renderer.py
        pdf_to_image.py
      metadata/
        metadata_writer.py
      utils/
        ids.py
        io.py
        seed.py
```

Onde fica cada responsabilidade:

- Geracao de tabelas: `synthetic_tables/src/generators/`.
- Exportacao base e despacho por formato: `synthetic_tables/src/exporters/`.
- Renderers de HTML, Markdown, LaTeX, PDF e imagens: `synthetic_tables/src/renderers/`.
- Templates HTML e LaTeX: `synthetic_tables/src/styles/templates/`.
- Amostragem de estilos e nomes de templates suportados: `synthetic_tables/src/styles/style_sampler.py`.
- Metadata JSONL: `synthetic_tables/src/metadata/metadata_writer.py`.
- Configuracao, paths e defaults: `synthetic_tables/src/config.py`.
- Pipeline principal: `synthetic_tables/src/main.py`.
- Diagnostico focado em LaTeX: `synthetic_tables/src/latex_smoke_test.py`.

## Mudancas Recentes De Organizacao E Implementacao

O projeto foi reorganizado em torno de um pipeline unico, com responsabilidades mais separadas:

- `main.py` passou a orquestrar geracao, exportacao, renderizacao, rasterizacao e metadata.
- `config.py` centraliza paths e parametros padrao como contagem de tabelas, versoes visuais, ranges de linhas/colunas, DPIs e formatos de origem.
- `FormatExporter` virou o ponto de despacho para CSV, XLSX, HTML, LaTeX e Markdown.
- `style_sampler.py` passou a concentrar estilos, templates suportados e IDs de estilo.
- HTML e LaTeX ficaram baseados em templates Jinja dentro de `styles/templates/`.
- Markdown continua sem templates Jinja; a composicao do documento vive em `markdown_renderer.py`.
- A conversao para PDF foi centralizada em `pdf_renderer.py`.
- A rasterizacao de PDFs ficou isolada em `pdf_to_image.py`.

Mudancas de layout/rendering:

- Foi adicionado o template `simple_tabular` como layout simples padrao para HTML, LaTeX e Markdown.
- O pipeline principal chama `StyleSampler.sample(...)` sem `layout_name`, entao a execucao padrao usa:
  - `simple_tabular.html.j2` para HTML;
  - `simple_tabular.tex.j2` para LaTeX;
  - `simple_tabular` para Markdown.
- Os templates alternativos continuam declarados em `TEMPLATE_NAMES_BY_FORMAT`, mas nao sao escolhidos aleatoriamente pelo `main.py` atual.
- HTML, Markdown e LaTeX agora adicionam uma coluna sintetica `Record` com valores `Record NNN` para preservar rastreabilidade das linhas.
- Tabelas largas passaram a ser divididas em blocos/matrizes com o mesmo `Record` repetido, em vez de tentar comprimir tudo em uma unica largura.
- O rendering LaTeX normal ficou estrito: ele exige um motor TeX real e nao troca automaticamente para ReportLab/xhtml2pdf no pipeline principal.

## Compatibilidade E Legado

Codigo de compatibilidade ainda presente:

- `synthetic_tables/src/renderers/pdf_renderer.py`
  - HTML tenta `playwright-chromium`, depois `weasyprint-html`, depois `xhtml2pdf-html-fallback`.
  - Markdown aceita o comentario legado `<!-- style: fonte/alinhamento/template -->`, alem do comentario atual `<!-- markdown-style: {...} -->`.
  - LaTeX possui `_latex_compatibility_source(...)`, que gera uma fonte LaTeX conservadora de safe-preview quando a compilacao criativa falha mas a tabela canonica pode ser extraida.
  - `_render_latex_without_tex_engine(...)` existe apenas para diagnosticos do smoke test; nao e fallback do pipeline normal.

- `synthetic_tables/src/renderers/markdown_renderer.py`
  - `_append_matrix_groups_legacy(...)` preserva a versao antiga do marcador de matriz com caractere especial. O fluxo atual usa `_append_matrix_groups(...)`, com separador ASCII `-`.

- `synthetic_tables/src/styles/templates/latex/default_table.tex.j2`
  - Template conservador de compatibilidade/debug para LaTeX.

- `synthetic_tables/src/exporters/xlsx_exporter.py`
  - `_export_with_zipfile(...)` permanece como fallback minimo caso `openpyxl` nao esteja disponivel.

- `synthetic_tables/src/exporters/format_exporter.py`
  - `export_render_bundle(...)` ainda existe como helper para exportar um pacote simples por formato. O pipeline atual usa caminhos versionados via `main.py`.

- `synthetic_tables/src/latex_smoke_test.py`
  - Gera um bundle de diagnostico em `synthetic_tables/data/rendered/diagnostics/<sample_stem>/`, incluindo logs, PDF nativo quando possivel, safe-preview e fallback forcado para comparacao.

O fallback nao-TeX de LaTeX e historico/diagnostico. No pipeline normal, se nenhum `latexmk`, `pdflatex` ou `tectonic` for encontrado, a renderizacao LaTeX falha com erro explicito.

## Regras Atuais De Renderizacao

### HTML

Regras principais em `synthetic_tables/src/renderers/html_renderer.py`:

- Usa templates Jinja em `synthetic_tables/src/styles/templates/html/`.
- O default do pipeline atual e `simple_tabular.html.j2`.
- Adiciona uma coluna visivel `Record`.
- Para o template simples, se houver mais de 5 colunas visiveis, divide a tabela em blocos `Block N`, mantendo `Record` em todos os blocos.
- Para tabelas com 6 ou mais colunas reais, ignora o modo de largura simples e calcula larguras semanticas por tipo de conteudo.
- Reduz escala de fonte em tabelas mais largas.
- Ajusta largura da folha conforme o template e a quantidade de colunas.

Conversao HTML -> PDF em `synthetic_tables/src/renderers/pdf_renderer.py`:

1. `playwright` + Chromium, caminho preferencial.
2. `weasyprint`, fallback de maior fidelidade.
3. `xhtml2pdf`, fallback de emergencia com CSS simplificado.

### Markdown

Regras principais em `synthetic_tables/src/renderers/markdown_renderer.py`:

- Markdown e montado programaticamente, sem templates Jinja.
- O default do pipeline atual e `simple_tabular`.
- O arquivo `.md` inclui no topo um comentario `markdown-style` em JSON com estilo e template.
- A tabela simples adiciona `Record` e divide tabelas largas em blocos de ate 5 colunas visiveis.
- Layouts alternativos suportados no codigo: `default_markdown`, `markdown_records`, `markdown_mixed` e `markdown_briefing`.
- Para layouts alternativos, datasets largos e ricos em strings podem virar `Matrix A`/`Matrix B`, sempre com ancoragem por `Record`.

Conversao Markdown -> PDF em `synthetic_tables/src/renderers/pdf_renderer.py`:

- Usa a biblioteca `markdown` com extensoes `tables` e `fenced_code`.
- Transforma Markdown em HTML tematico.
- Mapeia templates Markdown para temas HTML: `ledger`, `dossier`, `signal` e `briefing`.
- Renderiza o HTML resultante pelo mesmo caminho HTML -> PDF.

### LaTeX

Regras principais em `synthetic_tables/src/renderers/latex_renderer.py`:

- Usa templates Jinja em `synthetic_tables/src/styles/templates/latex/`.
- O default do pipeline atual e `simple_tabular.tex.j2`.
- Adiciona `Record` como coluna de rastreabilidade.
- Templates simples e safe-preview sao respeitados diretamente.
- Templates criativos podem ser redirecionados para `split_matrix.tex.j2` quando a tabela e larga ou muito categorica.
- O planner tenta layouts em ordem: `portrait`, `landscape`, `landscape-compact` e, se necessario, `split`.
- Cada detalhe dividido repete a coluna `Record`.
- Charts LaTeX aparecem nos templates criativos quando ha coluna numerica estavel e ate 75 linhas; os pontos sao divididos em paineis de ate 25 linhas.

Conversao LaTeX -> PDF em `synthetic_tables/src/renderers/pdf_renderer.py`:

- Procura motores nesta ordem: `latexmk`, `pdflatex`, `tectonic`.
- Tambem verifica variaveis de ambiente:
  - `SYNTHETIC_TABLES_LATEXMK` / `LATEXMK_PATH`
  - `SYNTHETIC_TABLES_PDFLATEX` / `PDFLATEX_PATH`
  - `SYNTHETIC_TABLES_TECTONIC` / `TECTONIC_PATH`
- Tambem tenta locais comuns de MiKTeX, TeX Live e TinyTeX no Windows.
- Compila primeiro a fonte criativa.
- Se a compilacao criativa falhar e a tabela puder ser extraida, tenta uma fonte LaTeX safe-preview.
- Se todas as tentativas TeX falharem, levanta erro; nao usa fallback nao-TeX no pipeline normal.

## Como Rodar

Os exemplos abaixo assumem PowerShell no Windows, a partir da raiz do repositorio.

### Instalar Dependencias

Crie e ative um ambiente virtual. A pasta `env/` na raiz e uma opcao simples:

```powershell
python -m venv env
.\env\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Se voce mantiver outro nome de venv, ajuste o prefixo dos comandos.

LaTeX e necessario para a execucao padrao porque `source_formats` inclui `latex`. Instale MiKTeX, TeX Live ou Tectonic, ou rode sem LaTeX usando `--source-formats html markdown`.

### Pipeline Completo

Com o ambiente ativado:

```powershell
python synthetic_tables\src\main.py
```

Sem ativar o ambiente:

```powershell
env\Scripts\python.exe synthetic_tables\src\main.py
```

### Rodar Sem LaTeX

```powershell
python synthetic_tables\src\main.py --source-formats html markdown
```

### Parametros Comuns

```powershell
python synthetic_tables\src\main.py --table-count 6
python synthetic_tables\src\main.py --visual-versions 3
python synthetic_tables\src\main.py --seed 123
python synthetic_tables\src\main.py --min-rows 50 --max-rows 120
python synthetic_tables\src\main.py --min-cols 4 --max-cols 14
python synthetic_tables\src\main.py --dpis 100 200 300
python synthetic_tables\src\main.py --source-formats html latex markdown
```

Exemplo completo:

```powershell
python synthetic_tables\src\main.py `
  --table-count 5 `
  --visual-versions 2 `
  --seed 77 `
  --min-rows 40 `
  --max-rows 90 `
  --min-cols 5 `
  --max-cols 10 `
  --dpis 100 300 `
  --source-formats html latex markdown
```

### Smoke Test De LaTeX

Depois de gerar ao menos uma fonte `.tex`:

```powershell
python synthetic_tables\src\latex_smoke_test.py --source synthetic_tables\data\rendered\latex\base_table_003__v02.tex
```

Se o executavel TeX nao estiver no `PATH`, informe o caminho por variavel de ambiente:

```powershell
$env:SYNTHETIC_TABLES_PDFLATEX = "C:\Path\To\pdflatex.exe"
python synthetic_tables\src\latex_smoke_test.py --source synthetic_tables\data\rendered\latex\base_table_003__v02.tex
```

Ou por argumento do smoke test:

```powershell
python synthetic_tables\src\latex_smoke_test.py --pdflatex-path "C:\Path\To\pdflatex.exe" --source synthetic_tables\data\rendered\latex\base_table_003__v02.tex
```

## Saidas Geradas

A execucao padrao grava:

- schemas em `synthetic_tables/data/base_tables/schemas/`
- CSVs em `synthetic_tables/data/base_tables/csv/`
- XLSX em `synthetic_tables/data/base_tables/xlsx/`
- HTML em `synthetic_tables/data/rendered/html/`
- LaTeX em `synthetic_tables/data/rendered/latex/`
- Markdown em `synthetic_tables/data/rendered/markdown/`
- PDFs em `synthetic_tables/data/rendered/pdf/`
- imagens PNG em `synthetic_tables/data/rendered/images/<sample_id>/`
- metadata de tabelas em `synthetic_tables/data/metadata/tables.jsonl`
- metadata de amostras em `synthetic_tables/data/metadata/samples.jsonl`

## Configuracao Padrao

Os defaults vivem em `synthetic_tables/src/config.py`:

- `table_count = 4`
- `visual_versions = 2`
- `seed = 42`
- `min_rows = 40`
- `max_rows = 100`
- `min_cols = 5`
- `max_cols = 12`
- `dpis = (100, 300)`
- `source_formats = ("html", "latex", "markdown")`

Formatos aceitos por `--source-formats`:

- `html`
- `latex`
- `markdown`

## Tipos De Dados Sinteticos

Os tipos de coluna suportados vivem em `synthetic_tables/src/generators/schema_generator.py`:

- `text_short`
- `text_long`
- `integer`
- `decimal`
- `percentage`
- `fraction`
- `date`
- `identifier`
- `alphanumeric_code`
- `symbolic_mixed`

## Dependencias

`requirements.txt` fica na raiz do repositorio e lista as dependencias diretas:

- `openpyxl`: exportacao XLSX.
- `Jinja2`: templates HTML e LaTeX.
- `markdown`: conversao Markdown -> HTML.
- `playwright`: renderizacao HTML -> PDF via Chromium.
- `weasyprint`: fallback HTML -> PDF.
- `reportlab`: renderizacao interna de previews/fallbacks diagnosticos.
- `xhtml2pdf`: fallback HTML de emergencia e preview diagnostico.
- `pypdfium2`: contagem/rasterizacao de PDFs.
- `Pillow`: suporte de imagem.

Notas:

- Playwright requer `python -m playwright install chromium`.
- WeasyPrint pode exigir bibliotecas nativas dependendo do sistema.
- O pipeline LaTeX normal exige `latexmk`, `pdflatex` ou `tectonic`.

## Limitacoes Atuais

- Ainda nao gera anotacoes OCR, bounding boxes ou segmentacao geometrica.
- Cada documento renderizado e centrado em uma tabela base.
- Layouts alternativos existem no codigo, mas o CLI atual nao expoe selecao de `layout_name`.
- O default inclui LaTeX; sem motor TeX instalado, use `--source-formats html markdown`.
- A metadata descreve artefatos e parametros, nao supervisao por celula.
- Degradacoes visuais como blur, skew, sombra, ruido e compressao ainda nao sao modeladas.

## Resumo End-To-End

Ao final de uma execucao bem sucedida, o projeto tera:

- criado tabelas base sinteticas;
- salvo schemas, CSVs e XLSX;
- gerado fontes HTML, LaTeX e/ou Markdown;
- renderizado PDFs;
- rasterizado paginas em PNG;
- escrito `tables.jsonl` e `samples.jsonl` para consumo programatico.
