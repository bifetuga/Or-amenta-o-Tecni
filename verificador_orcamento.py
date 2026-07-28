"""Protótipo: lê um XML de orçamento (formato de exemplo), aplica regras (rules.yaml) e produz um relatório JSON.
- Ajuste: mapeamento de categorias pode ser necessário para o seu XML real (PHC export).
- LLM: existe uma função stub; substitua pela integração com o seu modelo local (gpt4all/llama.cpp/transformers).
"""

import xml.etree.ElementTree as ET
import yaml
from collections import defaultdict
import json
import re
import sys
from pathlib import Path

RULES_PATH = "rules.yaml"


def load_rules(path=RULES_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_xml_to_dict(xml_path):
    """Parse um XML de orçamento para um dict simples.
    Este parser espera tags: <orcamento>, <cliente>, <itens><item> com <codigo>, <descricao>, <quantidade>, <categoria>, e <notas>.
    Adapte conforme o XML exportado pelo PHC — envie um ficheiro de exemplo e eu ajusto.
    """
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


def build_index_by_category(itens):
    idx = defaultdict(list)
    for it in itens:
        idx[it["categoria"]].append(it)
    return idx


def run_rule_checks(orcamento, rules):
    itens = orcamento["itens"]
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
        total = sum(it["quantidade"] for it in idx.get(cat, []))
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


def main(xml_path, out_json=None):
    rules = load_rules()
    orc = parse_xml_to_dict(xml_path)
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
        print("Uso: python verificador_orcamento.py exemplo_orcamento.xml [saida.json]")
        sys.exit(1)
    xml = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    main(xml, out)
