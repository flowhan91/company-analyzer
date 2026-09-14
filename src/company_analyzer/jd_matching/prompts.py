from __future__ import annotations

JD_PARSE_SYSTEM_PROMPT = """\
You are given the full text of a job description (JD), possibly in Korean, \
English, or a mix of both. Extract:

- role: a short job title/role name (e.g. "Backend Engineer", "AI Research \
  Engineer"), or null if not stated.
- role_subtype: a more specific specialization if stated or clearly implied \
  (e.g. "Search Infrastructure", "Machine Learning Platform"), else null.
- domain: a short topical tag matching the kind of tags used for company \
  news/events (e.g. "AI", "search", "commerce", "cloud", "infrastructure"), \
  else null.
- tasks: a list of concrete day-to-day responsibilities/tasks stated in the \
  JD, each as a short standalone phrase. Keep each task specific enough to \
  be matched against a real company's evidence of actually having done \
  similar work - avoid vague filler (e.g. "원활한 협업와 커뮤니케이션") unless the JD \
  genuinely has nothing more concrete.
- entities: any specific named technologies, products, or systems mentioned \
  in the JD's context/responsibilities (e.g. "Kubernetes", "HyperCLOVA X").
- skills: specific skills/technologies listed as requirements/qualifications \
  (may overlap with entities).

Preserve the JD's own wording and language in tasks/entities/skills - do not \
translate or paraphrase away specificity.
"""
