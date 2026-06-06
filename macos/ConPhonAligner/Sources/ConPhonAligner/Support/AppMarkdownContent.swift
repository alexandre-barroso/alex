import Foundation

enum AppMarkdownContent {
    static func help(language: AppLanguage) -> String {
        language == .portuguese ? helpPortuguese : helpEnglish
    }

    static func about(language: AppLanguage) -> String {
        language == .portuguese ? aboutPortuguese : aboutEnglish
    }

    private static let helpEnglish = """
    # ALEX - TextGrid Aligner and BioEar

    ALEX is a standalone macOS app. Select a folder; ALEX searches subfolders, validates filenames, converts readable audio to WAV mono 16 kHz when needed, and runs the hidden CLI while the interface stays responsive.

    ## Portuguese TextGrid alignment

    Portuguese needs same-folder audio / `.txt` pairs with the same stem:

    `sample_001.flac` + `sample_001.txt`

    ALEX converts readable audio to mono 16 kHz WAV first, then uses its BP speech engine to create `.TextGrid` files beside each pair. New BP TextGrids are created with canonical layer names: `phonemes`, `words`, `syllables`, and `utterance`. When existing TextGrids are found, ALEX asks whether to continue only for missing TextGrids or replace the existing TextGrids too.

    ## BioEar extraction

    Any language can be extracted when it has same-folder audio / `.txt` / `.TextGrid` trios with the same stem and identifiable TextGrid layers:

    `sample_001.m4a` + `sample_001.txt` + `sample_001.TextGrid`

    ALEX converts the audio to `sample_001.wav` first, writes `sample_001_bioear.h5` in that same folder, then enriches that same H5 with the selected IHC, synapse drive, and redocking datasets. The 4-character tag field stores your language/corpus stem in the H5 metadata; it does not limit extraction to a fixed list of languages.

    The preferred TextGrid layer names are `phonemes` or `phones`, `words`, `syllables` or `syl`, and optionally `sentence` or `utterance`. These names can appear in any layer number; ALEX identifies what is what by name. Sentence/utterance is optional; when absent, ALEX synthesizes one utterance for the file. Each audio file must contain only one sentence.

    ## Recognized TextGrid tiers

    Phones: `fonemas`, `fonemas-ipa`, `phone`, `phones`, `phoneme`, `phonemes`.

    Words: `pal_orto`, `grafemas`, `word`, `words`, `ortografia`, `orthography`, `hanzi`, `hanzis`.

    Syllables: `sil_fon`, `silabas-fonemas`, `silabas-fonemas-ipa`, `syllable`, `syllables`, `syl`, `pinyin`, `pinyins`.

    Sentence: `frase_orto`, `frase-grafemas`, `frase_fon`, `frase-fonemas`, `frase-fonemas-ipa`, `sentence`, `sentences`, `utterance`, `utterances`.

    Mandarin three-tier files are recognized as hanzis, pinyin, phones. ALEX maps hanzis to word/syllable, phones to phonemes, and synthesizes sentence from pinyin.

    ## BioEar options

    Modes: Fast, Balanced, Context-lite. Balanced is the production default.

    Rich arrays: IHC receptor potential, synapse drive, and redocking. Full rich Balanced is the default.

    ## Fail-safes

    ALEX blocks extraction when stems do not match, files are in different subfolders, audio is unreadable, TXT/TextGrid files are missing, or TextGrid tiers cannot be recognized. When this happens, the alert explains the fix and the log names the affected files.

    ## Safety

    The app does not load whole corpora into memory. Scanning runs away from the main interface, pair lists show a bounded preview, and extraction/resampling run as separate CLI processes with streamed progress.
    """

    private static let helpPortuguese = """
    # ALEX - Alinhador TextGrid e BioEar

    ALEX é um aplicativo macOS independente. Selecione uma pasta; ALEX pesquisa subpastas, valida nomes de arquivos, converte áudio legível para WAV mono 16 kHz quando necessário e executa a CLI oculta enquanto a interface permanece responsiva.

    ## Alinhamento TextGrid em português

    O português precisa de pares áudio / `.txt` na mesma pasta e com o mesmo stem:

    `sample_001.flac` + `sample_001.txt`

    ALEX converte áudio legível para WAV mono 16 kHz primeiro e depois usa seu motor BP para criar `.TextGrid` ao lado de cada par. Novos TextGrids BP já são criados com nomes canônicos de camadas: `phonemes`, `words`, `syllables` e `utterance`. Quando TextGrids existentes são encontrados, ALEX pergunta se deve continuar somente onde falta TextGrid ou substituir também os TextGrids existentes.

    ## Extração BioEar

    Qualquer língua pode ser extraída quando possui trios áudio / `.txt` / `.TextGrid` na mesma pasta, com o mesmo stem e camadas TextGrid identificáveis:

    `sample_001.m4a` + `sample_001.txt` + `sample_001.TextGrid`

    ALEX converte o áudio para `sample_001.wav` primeiro, grava `sample_001_bioear.h5` na mesma pasta e então enriquece esse mesmo H5 com IHC, synapse drive e redocking selecionados. O campo de tag com 4 caracteres armazena o stem da língua/corpus nos metadados H5; ele não limita a extração a uma lista fixa de línguas.

    Os nomes preferidos das camadas TextGrid são `phonemes` ou `phones`, `words`, `syllables` ou `syl` e, opcionalmente, `sentence` ou `utterance`. Esses nomes podem aparecer em qualquer número de camada; ALEX identifica cada função pelo nome. A camada sentence/utterance é opcional; quando ausente, ALEX sintetiza uma utterance única para o arquivo. Cada áudio deve conter apenas uma sentença.

    ## Camadas TextGrid reconhecidas

    Phones: `fonemas`, `fonemas-ipa`, `phone`, `phones`, `phoneme`, `phonemes`.

    Words: `pal_orto`, `grafemas`, `word`, `words`, `ortografia`, `orthography`, `hanzi`, `hanzis`.

    Syllables: `sil_fon`, `silabas-fonemas`, `silabas-fonemas-ipa`, `syllable`, `syllables`, `syl`, `pinyin`, `pinyins`.

    Sentence: `frase_orto`, `frase-grafemas`, `frase_fon`, `frase-fonemas`, `frase-fonemas-ipa`, `sentence`, `sentences`, `utterance`, `utterances`.

    Arquivos de mandarim com três camadas são reconhecidos como hanzis, pinyin e phones. ALEX mapeia hanzis para word/syllable, phones para phonemes e sintetiza sentence a partir de pinyin.

    ## Opções BioEar

    Modos: Rápido, Equilibrado, Contexto leve. Equilibrado é o padrão de produção.

    Matrizes ricas: potencial receptor IHC, synapse drive e redocking. Balanced rico completo é o padrão.

    ## Proteções

    ALEX bloqueia a extração quando stems não correspondem, arquivos estão em subpastas diferentes, áudio está ilegível, TXT/TextGrid estão ausentes ou camadas TextGrid não são reconhecidas. Quando isso acontece, o alerta explica a correção e o log nomeia os arquivos afetados.

    ## Segurança

    O app não carrega corpora inteiros na memória. O escaneamento roda fora da interface principal, listas mostram uma prévia limitada e extração/reamostragem rodam como processos CLI separados com progresso transmitido.
    """

    private static let aboutPortuguese = """
    # Sobre

    **ALEX - Alinhador TextGrid e BioEar** foi criado por **Alexandre Menezes Barroso** em **2026**.

    O módulo biológico usa `brucezilany` como único backend de periferia auditiva.

    O alinhamento TextGrid também se apoia no ecossistema livre do **Kaldi**, no **Kaldi-BR / Grupo FalaBrasil**, e no **Praat** para recursos, receitas de português brasileiro e validação de anotações. Agradecimentos adicionais às comunidades de **OpenFST**, **NumPy**, **SciPy**, **h5py** e **SoundFile**, que aparecem no backend ou nas rotas biológicas usadas pelo app.

    Este software é uma ferramenta local para alinhamento TextGrid e extração biológica de periferia auditiva.
    """

    private static let aboutEnglish = """
    # About

    **ALEX - TextGrid Aligner and BioEar** was created by **Alexandre Menezes Barroso** in **2026**.

    The biological module uses `brucezilany` as its auditory-periphery backend.

    TextGrid alignment also builds on the free **Kaldi**, **Kaldi-BR / Grupo FalaBrasil**, and **Praat** ecosystems for resources, Brazilian Portuguese recipes, and annotation validation. Additional thanks to the **OpenFST**, **NumPy**, **SciPy**, **h5py**, and **SoundFile** communities used by the backend and biological routes.

    This software is a local tool for TextGrid alignment and biological auditory-periphery extraction.
    """
}
