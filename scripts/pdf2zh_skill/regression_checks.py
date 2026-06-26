from __future__ import annotations

from .common import TRANSLATE, is_probably_untranslated
from .cli import (
    BILINGUAL_COLOR_NAME,
    bilingualize_caption_text_fragment,
    bilingualize_segment,
    localize_preserved_text_for_chinese,
    update_caption_arg_depth,
    with_bilingual_color_support,
    with_bilingual_frontmatter_spacing,
)
from .latex_ops import fix_translation, sanitize_latex_source, split_nodes


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_itemsep_not_split() -> None:
    source = r"\newenvironment{tight_itemize}{\begin{itemize} \itemsep" + "\n-2.1pt}{\\end{itemize}}\n"
    normalized = sanitize_latex_source(source)
    assert_true(r"\itemsep" in normalized, "sanitize_latex_source must preserve \\itemsep")
    assert_true(r"\item sep" not in normalized, "sanitize_latex_source must not split \\itemsep")


def test_inline_references_stay_with_translation_segment() -> None:
    source = "An overview of the method is shown in~\\autoref{fig:feature-extraction}."
    segments = [node.text for node in split_nodes(source) if node.kind == TRANSLATE]
    assert_true(
        any(r"\autoref{fig:feature-extraction}" in segment for segment in segments),
        "inline references should stay attached to the translated sentence",
    )


def test_reference_inventory_repair() -> None:
    original = "An overview is shown in~\\autoref{fig:feature-extraction}."
    translated = r"概览如~\Cref{...}所示。\autoref{fig:feature-extraction}"
    fixed = fix_translation(translated, original)
    assert_true(r"\Cref{...}" not in fixed, "placeholder references must be removed")
    assert_true(
        fixed.count(r"\autoref{fig:feature-extraction}") == 1,
        "reference inventory repair should keep exactly one original reference",
    )

    original = r"tool habits~\cite{viegas2007manyeyes,battle2018beagle}"
    translated = r"工具习惯~\cite{}\cite{viegas2007manyeyes,battle2018beagle}"
    fixed = fix_translation(translated, original)
    assert_true(r"\cite{}" not in fixed, "empty citations must be removed")
    assert_true(
        fixed.count(r"\cite{viegas2007manyeyes,battle2018beagle}") == 1,
        "duplicate citation repair should keep exactly one original citation",
    )

    original = "This sentence has no reference."
    translated = r"这个句子没有引用~\cite{invented2026}"
    fixed = fix_translation(translated, original)
    assert_true(r"\cite{invented2026}" not in fixed, "invented non-empty citations must be removed")

    original = r"Proof of identity \eqref{Yao-(3.1)-orth-simply}."
    translated = r"\eqref{\noindent \bf Proof of identity \eqref{Yao-(3.1)-orth-simply}.}"
    fixed = fix_translation(translated, original)
    assert_true(
        fixed == r"\eqref{Yao-(3.1)-orth-simply}",
        "nested/prose-corrupted reference keys must be restored from the original inventory",
    )

    original = ".\nThe underlying assumption is that \\textit{natural language contains redundancy \\citep{shannon1951prediction}"
    translated = "其基本假设是，自然语言中存在冗余信息。"
    fixed = fix_translation(translated, original)
    assert_true("其基本假设是" in fixed, "unbalanced source fragments must not force a full English fallback")
    assert_true(r"\citep{shannon1951prediction}" in fixed, "missing original citations should be appended to the translation")
    assert_true(r"\textit{natural language" not in fixed, "unbalanced original textit fragment must not leak into translation")


def test_frontmatter_title_can_be_segmented() -> None:
    source = (
        "\\documentclass{article}\n"
        "\\newcommand{\\papertitle}{Toward a Scalable Census of Dashboard Designs in the Wild}\n"
        "\\begin{document}\n"
        "\\title{\\papertitle}\n"
        "\\maketitle\n"
        "\\end{document}\n"
    )
    segments = [node.text for node in split_nodes(source) if node.kind == TRANSLATE]
    assert_true(
        any("Toward a Scalable Census" in segment for segment in segments),
        "title macro content should be translatable instead of fully protected",
    )


def test_identity_frontmatter_is_not_untranslated_warning() -> None:
    original = (
        r"\author{Michael Correll} \affiliation{ \institution{Tableau Research} "
        r"\city{Washington} \country{USA}} \email{mcorrell@tableau.com}"
    )
    translated = (
        r"\author{Michael Correll} \affiliation{ \institution{Tableau Research} "
        r"\city{华盛顿} \country{美国}} \email{mcorrell@tableau.com}"
    )
    assert_true(
        not is_probably_untranslated(original, translated),
        "author/email frontmatter should not be flagged as an untranslated prose segment",
    )

    original = r"\footnotetext[9]{https://python.langchain.com/docs/modules/data\_connection/document\_transformers/post\_retrieval/long\_context\_reorder}"
    translated = original
    assert_true(not is_probably_untranslated(original, translated), "URL-only footnotes should not be flagged as untranslated")

    original = r"), embedding-based methods (OpenAI-embedding, Voyageai\footnote{https://www.voyageai.com/}, BGE-large-en v1.5~\citep{bge_embedding}"
    translated = r")、基于嵌入的方法（OpenAI-embedding、Voyageai\footnote{https://www.voyageai.com/}、BGE-large-en v1.5~\citep{bge_embedding}"
    assert_true(not is_probably_untranslated(original, translated), "proper-noun list fragments should not be flagged as untranslated")


def test_control_word_cjk_and_missing_item_repair() -> None:
    source = r"\newcommand{\method}{UniPool}" + "\n" + r"\method中表现稳定。"
    normalized = sanitize_latex_source(source)
    assert_true(r"\method{}中" in normalized, "control words before CJK text need an explicit boundary")

    source = "\\begin{itemize}\n对于紧支撑的先验，我们证明结果。\n\\end{itemize}\n"
    normalized = sanitize_latex_source(source)
    assert_true(r"\item 对于紧支撑的先验" in normalized, "itemize prose must be restored as an item")


def test_econ_compile_normalizers() -> None:
    source = (
        "\\documentclass{article}\n"
        "{\\catcode/=0 \\catcode\\\\=12/gdef/mkillslash\\#1{#1}}\n"
        "\\edef\\jobnametmp{\\expandafter\\string\\csname embayes2_apx\\endcsname}\n"
        "\\edef\\jobnameapx{\\expandafter\\mkillslash\\jobnametmp}\n"
        "\\begin{document}\n\\end{document}\n"
    )
    normalized = sanitize_latex_source(source)
    assert_true(r"\edef\jobnameapx{embayes2" in normalized, "slash catcode jobname probe should be normalized")
    assert_true(r"\jobnametmp" not in normalized, "temporary slash-removal jobname helper should be removed")
    assert_true(r"\mkillslash" not in normalized, "unstable slash catcode helper should be removed")

    normalized = sanitize_latex_source(r"关于\（G\）、\（H\）的定义")
    assert_true(r"\（" not in normalized and r"\）" not in normalized, "escaped CJK punctuation should be unescaped")


def test_bilingual_plain_segment() -> None:
    output = bilingualize_segment(
        r"This method preserves citations~\cite{foo2024}. It also keeps formulas unchanged.",
        r"该方法保留引用~\cite{foo2024}。它还保持公式不变。",
    )
    assert_true(r"This method preserves citations~\cite{foo2024}." in output, "bilingual output must keep English prose")
    assert_true(r"该方法保留引用~\cite{foo2024}。" in output, "bilingual output must include Chinese prose")
    assert_true(rf"\color{{{BILINGUAL_COLOR_NAME}}}" in output, "Chinese bilingual prose must be green")
    assert_true(
        ".\n\n" not in output[: output.index(r"该方法保留引用~\cite{foo2024}。")],
        "Chinese sentence must follow the English sentence inline, not after a paragraph break",
    )
    assert_true(
        output.index(r"This method preserves citations~\cite{foo2024}.")
        < output.index(r"该方法保留引用~\cite{foo2024}。")
        < output.index("It also keeps formulas unchanged.")
        < output.index("它还保持公式不变。"),
        "plain bilingual prose must be interleaved sentence by sentence",
    )
    assert_true(r"\begingroup" not in output, "plain bilingual prose must not fall back to paragraph-level green blocks")


def test_bilingual_leading_continuation_punctuation_is_not_standalone() -> None:
    output = bilingualize_segment(
        r". A wide range of applications require long contexts~\cite{foo2024}",
        r"。广泛的应用需要长上下文~\cite{foo2024}。",
    )
    assert_true("A wide range of applications" in output, "continuation sentence text must remain")
    assert_true("广泛的应用需要长上下文" in output, "continuation sentence translation must remain")
    assert_true(not output.lstrip().startswith("."), "bilingual sentence output must not begin with a standalone English period")
    assert_true(not output.lstrip().startswith("。"), "bilingual sentence output must not begin with a standalone Chinese period")


def test_bilingual_structural_commands_do_not_duplicate() -> None:
    output = bilingualize_segment(
        "\\section{Introduction}\n\\label{sec:intro}\nThis paper introduces a method.",
        "\\section{引言}\n\\label{sec:intro}\n本文介绍了一种方法。",
    )
    assert_true(output.count(r"\section") == 1, "bilingual section must not duplicate section commands")
    assert_true(output.count(r"\label{sec:intro}") == 1, "bilingual section must not duplicate labels")
    assert_true(rf"\textcolor{{{BILINGUAL_COLOR_NAME}}}{{引言}}" in output, "translated section title must be green")
    assert_true("本文介绍了一种方法。" in output, "translated section body must be present")


def test_bilingual_caption_does_not_duplicate_label() -> None:
    output = bilingualize_segment(
        "\\caption{An overview of the method.}\n    \\label{fig:overview}",
        "\\caption{方法概览。}\n    \\label{fig:overview}",
    )
    assert_true(output.count(r"\caption") == 1, "bilingual caption must not duplicate caption commands")
    assert_true(output.count(r"\label{fig:overview}") == 1, "bilingual caption must not duplicate labels")
    assert_true("方法概览。" in output, "translated caption text must be present")


def test_bilingual_caption_merges_content_only_translation() -> None:
    output = bilingualize_segment(
        "\\caption{Distribution of compression ratio.\n}\n\\label{fig:dist}",
        "压缩比分布。",
    )
    assert_true(output.count(r"\caption") == 1, "content-only translated caption must keep one caption command")
    assert_true(r"\begingroup" not in output, "translated caption text must stay inline inside caption")
    assert_true("压缩比分布。" in output, "content-only translated caption text must be present")
    assert_true(output.count(r"\label{fig:dist}") == 1, "content-only translated caption must keep one label")


def test_bilingual_open_caption_fragment_stays_inline() -> None:
    output = bilingualize_segment(
        "\\caption{Distribution of compression ratio after chunk-wise compression.\n",
        "分块压缩后的压缩比分布。",
    )
    assert_true(output.count(r"\caption") == 1, "open caption fragment must keep one caption command")
    assert_true(r"\begingroup" not in output, "open caption fragment must not create a block inside caption")
    assert_true(r"\textcolor" in output, "open caption fragment must add inline green translation")
    assert_true(output.rstrip().endswith("}"), "open caption fragment must close only the green text group")


def test_bilingual_caption_context_text_fragment_stays_inline() -> None:
    depth = update_caption_arg_depth(0, "\\caption{\n")
    assert_true(depth > 0, "caption depth must be open after caption prefix")
    output = bilingualize_caption_text_fragment("Distribution of compression ratio.", "压缩比分布。")
    assert_true(r"\begingroup" not in output, "caption text fragment must not create a block")
    assert_true(r"\textcolor" in output, "caption text fragment must add inline green translation")
    depth = update_caption_arg_depth(depth, output + "\n}")
    assert_true(depth == 0, "caption depth must close after caption suffix")


def test_bilingual_title_context_text_fragment_stays_inline() -> None:
    depth = update_caption_arg_depth(0, "\\title{\n", {"title"})
    assert_true(depth > 0, "title depth must be open after title prefix")
    output = bilingualize_caption_text_fragment("English Paper Title", "中文论文标题")
    assert_true(r"\begingroup" not in output, "title text fragment must not create a block")
    assert_true(r"\textcolor" in output, "title text fragment must add inline green translation")
    depth = update_caption_arg_depth(depth, output + "\n}", {"title"})
    assert_true(depth == 0, "title depth must close after title suffix")


def test_bilingual_unbalanced_original_fragment_stays_inline() -> None:
    output = bilingualize_segment(
        r"The assumption is \textit{natural language contains redundancy \citep{foo2024}",
        r"其假设是自然语言存在冗余 \citep{foo2024}。",
    )
    assert_true(r"\begingroup" not in output, "unbalanced original fragments must not receive block translations")
    assert_true(r"\textcolor" in output, "unbalanced original fragments must receive inline green translations")
    assert_true("其假设是自然语言存在冗余" in output, "inline translation text must remain")


def test_bilingual_caption_inline_latex_is_normalized() -> None:
    output = bilingualize_segment(
        r"\caption{Color examples.}",
        r"\caption{\textcolor{蓝色}{blue} and \hl{变异性}.}",
    )
    assert_true(r"\textcolor{blue}{蓝色}" in output, "translated color names must not become xcolor names")
    assert_true(r"\textbf{变异性}" in output, "translated hl content must be made soul-safe")
    assert_true("蓝色" in output and "变异性" in output, "normalized translated caption text must remain")


def test_bilingual_item_does_not_duplicate_item() -> None:
    output = bilingualize_segment(
        r"\item We keep citation keys unchanged~\cite{foo2024}.",
        r"\item 我们保持引用键不变~\cite{foo2024}。",
    )
    assert_true(output.count(r"\item") == 1, "bilingual item must not duplicate item markers")
    assert_true(r"citation keys unchanged~\cite{foo2024}" in output, "English item body must remain")
    assert_true(r"我们保持引用键不变~\cite{foo2024}。" in output, "Chinese item body must be present")


def test_bilingual_multi_item_segment_does_not_color_item_commands() -> None:
    output = bilingualize_segment(
        "[label=\\arabic*),topsep=1pt,itemsep=2pt,leftmargin=20pt]\n"
        r"\item First contribution. "
        r"\item Second contribution.",
        "[label=\\arabic*),topsep=1pt,itemsep=2pt,leftmargin=20pt]\n"
        r"\item 第一项贡献。 "
        r"\item 第二项贡献。",
    )
    assert_true(output.count(r"\item") == 2, "multi-item bilingual output must keep only original item commands")
    assert_true("[label=" not in output, "enumerate option noise must not be rendered as item text")
    assert_true("第一项贡献。" in output and "第二项贡献。" in output, "multi-item Chinese text must remain")


def test_bilingual_identity_segment_is_preserved_once() -> None:
    output = bilingualize_segment(r"\maketitle", r"\maketitle")
    assert_true(output == r"\maketitle", "identity bilingual segment must be preserved once")
    assert_true(BILINGUAL_COLOR_NAME not in output, "identity bilingual segment must not be colored")


def test_bilingual_executable_commands_do_not_repeat_in_green_block() -> None:
    output = bilingualize_segment(
        "\\maketitle\n\\footnotetext[1]{Work during internship.}",
        "\\maketitle\n\\footnotetext[1]{在实习期间完成。}",
    )
    assert_true(output.count(r"\maketitle") == 1, "bilingual output must not repeat maketitle")
    assert_true("在实习期间完成。" in output, "translated footnote text must remain")
    assert_true(BILINGUAL_COLOR_NAME in output, "translated footnote text must be green")


def test_bilingual_open_resizebox_tail_stays_outside_argument() -> None:
    output = bilingualize_segment(
        "}\\\\\nEnglish answer.\\\\\n\\resizebox{\\columnwidth}{!}{",
        "}\\\\\n中文回答。\\\\\n\\resizebox{\\columnwidth}{!}{",
    )
    assert_true(output.count(r"\resizebox{\columnwidth}{!}{") == 1, "open resizebox tail must not be duplicated")
    assert_true("中文回答。" in output, "translated resizebox-tail segment text must remain")
    assert_true(output.index("中文回答。") < output.index(r"\resizebox{\columnwidth}{!}{"), "green text must stay before the open resizebox")


def test_preserved_reference_tail_is_localized() -> None:
    output = localize_preserved_text_for_chinese(" for detailed information.\n")
    assert_true("for detailed information" not in output, "preserved prose tail must be localized")
    assert_true("，以了解详细信息" in output, "localized preserved prose tail must remain meaningful")
    output = localize_preserved_text_for_chinese(", \\citet{foo2024}, and \\citet{bar2025}")
    assert_true(" and " not in output, "preserved citation lists must not keep English connectors")
    assert_true("、\\citet{foo2024} 和 \\citet{bar2025}" in output, "preserved citation lists must use Chinese connectors")


def test_bilingual_color_support_is_injected() -> None:
    source = "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n"
    output = with_bilingual_color_support(source)
    assert_true(r"\usepackage{xcolor}" in output, "bilingual output must load xcolor when missing")
    assert_true(
        rf"\definecolor{{{BILINGUAL_COLOR_NAME}}}{{RGB}}{{0,128,0}}" in output,
        "bilingual output must define the green Chinese color",
    )


def test_bilingual_frontmatter_spacing_is_injected() -> None:
    source = "\\renewcommand{\\thefootnote}{\\arabic{footnote}}  \n\\begin{abstract}\nText"
    output = with_bilingual_frontmatter_spacing(source)
    assert_true(r"\vspace*{7.0em}" in output, "bilingual frontmatter must add spacing before abstract")
    assert_true(output.count(r"\begin{abstract}") == 1, "bilingual spacing must not duplicate abstract")


def main() -> int:
    tests = [
        test_itemsep_not_split,
        test_inline_references_stay_with_translation_segment,
        test_reference_inventory_repair,
        test_frontmatter_title_can_be_segmented,
        test_identity_frontmatter_is_not_untranslated_warning,
        test_control_word_cjk_and_missing_item_repair,
        test_econ_compile_normalizers,
        test_bilingual_plain_segment,
        test_bilingual_leading_continuation_punctuation_is_not_standalone,
        test_bilingual_structural_commands_do_not_duplicate,
        test_bilingual_caption_does_not_duplicate_label,
        test_bilingual_caption_merges_content_only_translation,
        test_bilingual_open_caption_fragment_stays_inline,
        test_bilingual_caption_context_text_fragment_stays_inline,
        test_bilingual_title_context_text_fragment_stays_inline,
        test_bilingual_unbalanced_original_fragment_stays_inline,
        test_bilingual_caption_inline_latex_is_normalized,
        test_bilingual_item_does_not_duplicate_item,
        test_bilingual_multi_item_segment_does_not_color_item_commands,
        test_bilingual_identity_segment_is_preserved_once,
        test_bilingual_executable_commands_do_not_repeat_in_green_block,
        test_bilingual_open_resizebox_tail_stays_outside_argument,
        test_preserved_reference_tail_is_localized,
        test_bilingual_color_support_is_injected,
        test_bilingual_frontmatter_spacing_is_injected,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"regression checks passed: {len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
