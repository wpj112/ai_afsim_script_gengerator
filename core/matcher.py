from dataclasses import dataclass
import re

@dataclass
class MatchResult:
    rule_id: str
    confidence: str
    matched_text: str
    line_no: int
    fix: dict
    lessons: list[str]

def match_output(stdout: str, stderr: str, rules: dict) -> list[MatchResult]:
    combined = (stdout + "\n" + stderr) if stdout else stderr
    results = []
    for rule in rules.get("rules", []):
        for kw in rule.get("keywords", []):
            for i, line in enumerate(combined.splitlines(), 1):
                if kw.lower() in line.lower():
                    results.append(MatchResult(rule["id"], "exact", line, i,
                                               rule.get("fix", {}), rule.get("lessons", [])))
                    break
            else:
                continue
            break
        else:
            for pat in rule.get("patterns", []):
                for i, line in enumerate(combined.splitlines(), 1):
                    if re.search(pat, line):
                        results.append(MatchResult(rule["id"], "pattern", line, i,
                                                   rule.get("fix", {}), rule.get("lessons", [])))
                        break
                else:
                    continue
                break
    return results
