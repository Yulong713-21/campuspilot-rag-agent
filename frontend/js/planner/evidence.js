const sourceTypeLabels = {
  program_handbook: "PROGRAM HANDBOOK",
  unit_handbook: "UNIT HANDBOOK",
  official_handbook: "OFFICIAL HANDBOOK",
  official_course_map: "COURSE MAP",
  official_course_page: "COURSE PAGE",
  official_unit_page: "UNIT PAGE",
  official_government_policy: "GOVERNMENT POLICY",
};

function clip(text, length = 260) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  return normalized.length > length ? `${normalized.slice(0, length).trim()}…` : normalized;
}

function evidenceCard(item, index) {
  const article = document.createElement("article");
  article.className = "evidence-card";

  const top = document.createElement("div");
  top.className = "evidence-card-top";
  const sequence = document.createElement("span");
  const type = document.createElement("span");
  sequence.textContent = String(index + 1).padStart(2, "0");
  type.textContent = sourceTypeLabels[item.source_type] || String(item.source_type || "OFFICIAL SOURCE").replaceAll("_", " ").toUpperCase();
  top.append(sequence, type);

  const title = document.createElement("h3");
  title.textContent = item.title || item.heading || "Official source";

  const heading = document.createElement("p");
  heading.className = "evidence-card-heading";
  heading.textContent = item.heading || `Handbook ${item.handbook_year || 2026}`;

  const excerpt = document.createElement("p");
  excerpt.className = "evidence-excerpt";
  excerpt.textContent = clip(item.content || item.parent_content || "本次规划引用了该官方来源。", 300);

  const footer = document.createElement("div");
  footer.className = "evidence-card-footer";
  const meta = document.createElement("span");
  const channels = Array.isArray(item.retrieval_channels) ? item.retrieval_channels.join(" + ") : "verified";
  meta.textContent = `${channels.toUpperCase()} · ${item.handbook_year || 2026}`;
  const link = document.createElement("a");
  link.href = item.source_url || item.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "打开官方原文 ↗";
  footer.append(meta, link);

  article.append(top, title, heading, excerpt, footer);
  return article;
}

export function renderEvidence({ container, count, section, payload, catalogSources }) {
  const retrieved = Array.isArray(payload.evidence) ? payload.evidence : [];
  const sourceMap = new Map(catalogSources.map((source) => [source.source_id, source]));
  const fallback = (payload.source_ids || [])
    .map((sourceId) => sourceMap.get(sourceId))
    .filter(Boolean);
  const seen = new Set();
  const items = [...retrieved, ...fallback].filter((item) => {
    const key = item.source_url || item.url || item.document_id || item.source_id;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  container.replaceChildren(...items.map(evidenceCard));
  count.textContent = String(items.length);
  section.classList.toggle("hidden", items.length === 0);
}
