"""Protótipo: lê um XML de orçamento (formato de exemplo ou export PHC BO.xml), aplica regras (rules.yaml) e produz um relatório JSON.
Este ficheiro foi atualizado para detectar e suportar a exportação PHC (BO.xml) fornecida.

- Se for um ficheiro PHC (root tag VFPData com elemento <bo>), usamos parse_phc_bo() para extrair os campos de cabeçalho.
- Para validações de compatibilidade (equipamentos necessários / incompatibilidades) precisamos das linhas do orçamento (export PHC das linhas). Se tiver um ficheiro separado com as linhas (normalmente export chamado "bolinhas" ou "bol" / "bolinha" / "bol_linha"), envie-o e eu adapto a leitura das linhas.

Uso:
  python verificador_orcamento.py BO.xml
  (gera relatório JSON para stdout ou grava para ficheiro se indicar saída)
"""

import xml.etree.ElementTree as ET
import yaml
from collections import defaultdict
import json
import re
import sys
from pathlib import Path
from typing import Dict, Any, List

RULES_PATH = "rules.yaml"


def load_rules(path=RULES_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_generic_xml_to_dict(xml_path: str) -> Dict[str, Any]:
    """Fallback parser for a simple XML structure with <orcamento> root (previous example)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    orc = {"id": root.attrib.get("id"), "cliente": None, "itens": [], "notas": None}
    cliente = root.find("cliente")
    if cliente is not None:
        orc["cliente"] = cliente.text
    notas = root.find("notas")
    if notas is not None:
        orc["notas"] = notas.text
    # Procura por todos os elementos <item>
    for item in root.findall('.//item'):
        codigo = item.findtext("codigo")
        descricao = item.findtext("descricao")
        quantidade_txt = item.findtext("quantidade") or "1"
        try:
            quantidade = int(float(quantidade_txt))
        except Exception:
            quantidade = 1
        categoria = item.findtext("categoria") or ""
        orc["itens"].append({
            "codigo": codigo,
            "descricao": descricao,
            "quantidade": quantidade,
            "categoria": categoria
        })
    return orc


def parse_phc_bo(xml_path: str) -> Dict[str, Any]:
    """Parses PHC BO.xml export (header only) into our normalized orcamento dict.

    Notes:
    - This file (BO.xml) contains the BO header. Line items are commonly exported in a separate file (e.g., BOLINHA/bol_linha).
    - This function extracts header fields (cliente, id, notas, totals, morada, moeda, vendedor, etc.).
    - If line items are embedded (not in this sample), the parser will try to find them under the root.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Find first <bo> element
    bo = root.find('.//bo')
    if bo is None:
        # fallback
        return parse_generic_xml_to_dict(xml_path)

    def text(tag: str) -> str:
        el = bo.find(tag)
        return el.text.strip() if (el is not None and el.text) else ""

    def num(tag: str) -> float:
        t = text(tag)
        if not t:
            return 0.0
        # normalize comma/decimal
        t = t.replace(',', '.')
        try:
            return float(t)
        except Exception:
            # some fields use ".000" format
            try:
                return float(re.sub(r"[^0-9.-]", "", t))
            except Exception:
                return 0.0

    # Basic normalization
    orc = {
        "id": text("boid") or text("obrano"),
        "cliente": text("nome") or text("nome2"),
        "notas": text("obs") or (text("trab1") + " " + text("trab2")).strip() or None,
        "moeda": text("moeda"),
        "total": num("total") or num("bo_1tvall") or num("bo_2tvall"),
        "custo": num("custo"),
        "ndos": text("ndos"),
        "local": text("local"),
        "morada": text("morada"),
        "codpost": text("codpost"),
        "zona": text("zona"),
        "usuario": text("usrinis") or text("ousrinis"),
        "itens": []  # lines usually in a separate export
    }

    # Try to extract lines if present in the same file (common PHC exports separate lines)
    # PHC line tables sometimes named "bolinha" or similar; we try to detect child elements that look like lines
    possible_lines = []
    # Heuristic: find elements named 'bol', 'bolinha', 'bol_linha', 'bol_linhas', 'linhas', 'bo_linha'
    candidates = ['bol', 'bolinha', 'bol_linha', 'linhas', 'l', 'bl', 'rol', 'bolinhas', 'linha']
    for name in candidates:
        for el in root.findall('.//'+name):
            possible_lines.append(el)
    # Generic fallback: any child elements under root that have subelements like 'codigo' or 'artigo' or 'quantidade'
    if not possible_lines:
        for child in root:
            for sub in list(child):
                taglower = sub.tag.lower()
                if 'art' in taglower or 'cod' in taglower or 'quant' in taglower or 'preco' in taglower:
                    # assume child is a line-like element
                    possible_lines.append(child)
                    break

    # If we found candidate line elements, try to extract basic fields
    if possible_lines:
        for line in possible_lines:
            # each 'line' may itself contain multiple items (if it's a container), so iterate its children
            if list(line):
                # if child tags are line items
                for li in list(line):
                    code = (li.findtext('codigo') or li.findtext('artigo') or li.findtext('ref') or '').strip()
                    desc = (li.findtext('descricao') or li.findtext('designacao') or li.findtext('desc') or '').strip()
                    qty_txt = (li.findtext('quantidade') or li.findtext('qtd') or li.findtext('quant') or '1')
                    try:
                        qty = int(float(qty_txt.replace(',', '.')))
                    except Exception:
                        qty = 1
                    categoria = (li.findtext('categoria') or li.findtext('grupo') or '').strip()
                    possible_price = li.findtext('valor') or li.findtext('preco') or li.findtext('valorvenda') or ''
                    price = 0.0
                    if possible_price:
                        try:
                            price = float(possible_price.replace(',', '.'))
                        except Exception:
                            price = 0.0
                    orc['itens'].append({
                        'codigo': code,
                        'descricao': desc,
                        'quantidade': qty,
                        'categoria': categoria,
                        'preco_unit': price
                    })
            else:
                # single element that looks like a line
                li = line
                code = (li.findtext('codigo') or li.findtext('artigo') or li.findtext('ref') or '').strip()
                desc = (li.findtext('descricao') or li.findtext('designacao') or li.findtext('desc') or '').strip()
                qty_txt = (li.findtext('quantidade') or li.findtext('qtd') or li.findtext('quant') or '1')
                try:
                    qty = int(float(qty_txt.replace(',', '.')))
                except Exception:
                    qty = 1
                categoria = (li.findtext('categoria') or li.findtext('grupo') or '').strip()
                possible_price = li.findtext('valor') or li.findtext('preco') or li.findtext('valorvenda') or ''
                price = 0.0
                if possible_price:
                    try:
                        price = float(possible_price.replace(',', '.'))
                    except Exception:
                        price = 0.0
                orc['itens'].append({
                    'codigo': code,
                    'descricao': desc,
                    'quantidade': qty,
                    'categoria': categoria,
                    'preco_unit': price
                })

    return orc


def build_index_by_category(itens):
    idx = defaultdict(list)
    for it in itens:
        # allow empty category -> use description to guess later
        idx[it.get("categoria", "")] .append(it)
    return idx


def run_rule_checks(orcamento, rules):
    itens = orcamento.get("itens", [])
    idx = build_index_by_category(itens)
    issues = []
    # requires
    requires = rules.get("requires", {})
    for cat, reqs in requires.items():
        if idx.get(cat):
            for req in reqs:
                if not idx.get(req):
                    issues.append({
                        "type": "missing_required",
                        "for_category": cat,
                        "required": req,
                        "message": f"Categoria '{cat}' requer '{req}' mas não foi encontrada."
                    })
    # incompatible
    for pair in rules.get("incompatible", []):
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        a, b = pair[0], pair[1]
        if idx.get(a) and idx.get(b):
            issues.append({
                "type": "incompatible",
                "pair": pair,
                "message": f"Categorias incompatíveis encontradas: {a} e {b}."
            })
    # min_quantity
    min_q = rules.get("min_quantity", {})
    for cat, minc in min_q.items():
        total = sum(it.get("quantidade", 0) for it in idx.get(cat, []))
        if total < minc:
            issues.append({
                "type": "min_quantity",
                "category": cat,
                "found": total,
                "required": minc,
                "message": f"Categoria '{cat}' tem {total}, precisa de pelo menos {minc}."
            })
    # notes checks (basic)
    nr = rules.get("notes_requirements", [])
    notes = orcamento.get("notas", "") or ""
    for check in nr:
        pattern = check.get("pattern")
        if not pattern:
            continue
        if re.search(pattern, notes, re.I):
            for f in check.get("required_fields", []):
                if f not in notes:
                    issues.append({
                        "type": "notes_missing_field",
                        "pattern": pattern,
                        "required_field": f,
                        "message": f"Nota menciona '{pattern}' mas não contém '{f}'."
                    })
    return issues


def llm_review_notes_stub(notes, issues_summary):
    """Substitua por chamada ao seu LLM local.
    Exemplo de integração está documentado no README.
    """
    return {
        "llm_available": False,
        "improved_notes": None,
        "comment": "LLM local não configurado — substitua esta função pela chamada ao seu modelo."
    }


def generate_report(orcamento, issues, llm_result):
    report = {
        "orcamento": orcamento,
        "issues": issues,
        "llm_review": llm_result
    }
    return report


def detect_and_parse(xml_path: str) -> Dict[str, Any]:
    """Detect format and parse accordingly.
    - If PHC BO export (root VFPData with <bo>) -> parse_phc_bo
    - Else fallback to generic parser
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        # PHC export uses VFPData root and <bo> elements
        if root.tag.lower().endswith('vfpdata') or root.find('.//bo') is not None:
            return parse_phc_bo(xml_path)
    except ET.ParseError:
        # fallback to generic
        pass
    return parse_generic_xml_to_dict(xml_path)


def main(xml_path, out_json=None):
    rules = load_rules()
    orc = detect_and_parse(xml_path)
    issues = run_rule_checks(orc, rules)
    llm_result = llm_review_notes_stub(orc.get("notas", ""), issues)
    report = generate_report(orc, issues, llm_result)
    out = json.dumps(report, ensure_ascii=False, indent=2)
    if out_json:
        Path(out_json).write_text(out, encoding="utf-8")
        print(f"Relatório escrito em: {out_json}")
    else:
        print(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python verificador_orcamento.py exemplo_orcamento.xml ou python verificador_orcamento.py BO.xml [saida.json]")
        sys.exit(1)
    xml = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    main(xml, out)
