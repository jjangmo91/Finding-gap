// 발견공백 대화형 도우미 — Supabase Edge Function.
// 로그인 사용자의 질문을 Gemini(함수호출)로 처리하고, 도구는 fg_* 참조 테이블(DB 직결)만 조회한다.
// 배포: supabase functions deploy chat   ·   비밀키: supabase secrets set GEMINI_API_KEY=...
// 기본 주입 비밀(SUPABASE_URL/ANON_KEY/DB_URL)은 Supabase가 제공. 원시 좌표·개인정보는 노출하지 않는다.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import postgres from "https://deno.land/x/postgresjs@v3.4.5/mod.js";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const GEMINI_KEY = Deno.env.get("GEMINI_API_KEY") ?? "";
const MODEL = Deno.env.get("GEMINI_MODEL") ?? "gemini-2.0-flash";
const DAILY_CAP = Number(Deno.env.get("CHAT_DAILY_CAP") ?? "20");
const MAX_STEPS = 4;               // 에이전트 루프 상한(툴 호출 왕복)
const MAX_HISTORY = 12;            // 클라이언트가 보내는 대화 이력 상한
const GEMINI_TIMEOUT_MS = 10000;   // Gemini 호출당 타임아웃
const BUDGET_MS = 20000;           // 전체 처리 예산(초과 시 루프 중단)

const sql = postgres(Deno.env.get("SUPABASE_DB_URL")!, { prepare: false, max: 5 });

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, apikey, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });

// ── 발견 상태 기준: found=최근10년 기록 · dormant=오래된 기록 · undiscovered=기록없음 ──
const CUTOFF = new Date().getFullYear() - 10;
const THREAT = ["CR", "EN", "VU", "NT"];

const regionField = (code: string) => (code.length === 2 ? "sido" : "region");
const asList = (v: unknown): string[] =>
  v == null ? [] : String(v).split(/[,;]/).map((s) => s.trim()).filter(Boolean);
const normGrade = (v: unknown) =>
  asList(v).map((x) => x.toUpperCase().replace("급", "")).map((x) => ({ "1": "I", "2": "II" }[x] ?? x));
const normRedlist = (v: unknown) => asList(v).map((x) => x.toUpperCase());

// ─────────────────────────── 도구(fg_* 조회) ───────────────────────────

async function findRegion(a: Record<string, unknown>) {
  const name = String(a.name ?? "").trim();
  if (!name) return { error: "지역 이름이 필요합니다." };
  const rows = await sql`
    select code, name, level from fg_region
    where name like ${"%" + name + "%"}
    order by level, code limit 20`;
  return { regions: rows, note: rows.length ? "code 를 다른 도구의 region 인자로 사용하세요." : "일치하는 지역이 없습니다." };
}

async function regionDiscoverySummary(a: Record<string, unknown>) {
  const code = String(a.region ?? "").trim();
  if (code.length !== 2 && code.length !== 5) return { error: "region 은 시도(2자리) 또는 시군구(5자리) 코드여야 합니다. find_region 으로 코드를 찾으세요." };
  const col = regionField(code);
  const tg = a.taxon_group ? String(a.taxon_group) : null;
  const region = (await sql`select code, name, level from fg_region where code = ${code} limit 1`)[0];
  const rec = (await sql`
    select count(*)::int recorded, count(*) filter (where my >= ${CUTOFF})::int found from (
      select sr.ktsn, max(sr.maxyear) my
      from fg_species_region sr
      where sr.${sql(col)} = ${code} ${tg ? sql`and sr.taxon_group = ${tg}` : sql``}
      group by sr.ktsn) t`)[0];
  const total = (await sql`select coalesce(sum(n_species),0)::int c from fg_taxa ${tg ? sql`where taxon_group = ${tg}` : sql``}`)[0].c;
  return {
    region: code, region_name: region?.name ?? null, level: region?.level ?? null,
    taxon_group: tg, reference_year: CUTOFF + 10,
    summary: { total, found: rec.found, dormant: rec.recorded - rec.found, undiscovered: total - rec.recorded, recorded: rec.recorded },
  };
}

async function undiscoveredPrioritySpecies(a: Record<string, unknown>) {
  const code = String(a.region ?? "").trim();
  if (code.length !== 2 && code.length !== 5) return { error: "region 은 시도(2자리) 또는 시군구(5자리) 코드여야 합니다. find_region 으로 코드를 찾으세요." };
  const col = regionField(code);
  const tg = a.taxon_group ? String(a.taxon_group) : null;
  const grade = normGrade(a.endangered_grade);
  const rl = normRedlist(a.redlist_category);
  const limit = Math.max(1, Math.min(Number(a.limit ?? 15), 50));
  const rows = await sql`
    select s.ktsn, s.korean_name, s.scientific_name, s.taxon_group, s.taxon_group_kor,
           s.endangered_grade, s.national_redlist_category, s.interest
    from fg_species s
    where 1=1
      ${tg ? sql`and s.taxon_group = ${tg}` : sql``}
      ${grade.length ? sql`and s.endangered_grade = any(${grade})` : sql``}
      ${rl.length ? sql`and coalesce(s.national_redlist_category,'') = any(${rl})` : sql``}
      and not exists (select 1 from fg_species_region r where r.ktsn = s.ktsn and r.${sql(col)} = ${code})
    order by s.interest desc nulls last, s.korean_name
    limit ${limit}`;
  return {
    region: code, taxon_group: tg, count: rows.length, species: rows,
    note: "미발견 종을 관심도(interest) 높은 순으로. 실제 조사 계획엔 서식·계절 정보가 별도로 필요합니다.",
  };
}

async function searchSpecies(a: Record<string, unknown>) {
  const q = String(a.query ?? "").trim().toLowerCase();
  if (!q) return { error: "검색어가 필요합니다." };
  const like = "%" + q + "%", pref = q + "%";
  const limit = Math.max(1, Math.min(Number(a.limit ?? 10), 30));
  const rows = await sql`
    select ktsn, korean_name, scientific_name, taxon_group, taxon_group_kor,
           endangered_grade, national_redlist_category, interest
    from fg_species
    where lower(korean_name) like ${like} or lower(scientific_name) like ${like}
    order by (case when lower(korean_name) like ${pref} then 0 when lower(scientific_name) like ${pref} then 1 else 2 end),
             length(korean_name)
    limit ${limit}`;
  return { count: rows.length, species: rows };
}

async function speciesDetail(a: Record<string, unknown>) {
  const ktsn = String(a.ktsn ?? "").trim();
  const sp = (await sql`
    select ktsn, korean_name, scientific_name, taxon_group, taxon_group_kor,
           endangered_grade, national_redlist_category, interest
    from fg_species where ktsn = ${ktsn} limit 1`)[0];
  if (!sp) return { error: `종을 찾을 수 없습니다: ktsn=${ktsn}. search_species 로 ktsn 을 찾으세요.` };
  const agg = (await sql`
    select count(*)::int n_regions, max(maxyear) maxyear, coalesce(sum(obs_count),0)::bigint obs,
           count(*) filter (where maxyear >= ${CUTOFF})::int found_regions
    from fg_species_region where ktsn = ${ktsn}`)[0];
  const my = agg.maxyear as number | null;
  const state = !my ? "undiscovered" : my >= CUTOFF ? "found" : "dormant";
  return {
    ...sp, reference_year: CUTOFF + 10, national_discovery_state: state, national_max_year: my,
    recorded_regions: agg.n_regions, found_regions: agg.found_regions, total_observations: Number(agg.obs),
  };
}

async function listProtectedSpecies(a: Record<string, unknown>) {
  const grade = normGrade(a.endangered_grade);
  const rl = normRedlist(a.redlist_category);
  const isDefault = grade.length === 0 && rl.length === 0;
  const tg = a.taxon_group ? String(a.taxon_group) : null;
  const limit = Math.max(1, Math.min(Number(a.limit ?? 30), 100));
  const filt = sql`
    ${tg ? sql`and s.taxon_group = ${tg}` : sql``}
    ${grade.length ? sql`and s.endangered_grade = any(${grade})` : sql``}
    ${rl.length ? sql`and coalesce(s.national_redlist_category,'') = any(${rl})` : sql``}
    ${isDefault ? sql`and (coalesce(s.endangered_grade,'') <> '' or coalesce(s.national_redlist_category,'') = any(${THREAT}))` : sql``}`;
  const code = String(a.region ?? "").trim();
  if (code && code.length !== 2 && code.length !== 5) return { error: "region 은 시도(2자리)·시군구(5자리) 코드여야 합니다." };
  if (code) {
    const col = regionField(code);
    const state = String(a.state ?? "undiscovered").toLowerCase();
    const region = (await sql`select name, level from fg_region where code = ${code} limit 1`)[0];
    const rows = await sql`
      select s.ktsn, s.korean_name, s.scientific_name, s.taxon_group, s.taxon_group_kor,
             s.endangered_grade, s.national_redlist_category, s.interest
      from fg_species s
      where 1=1 ${filt}
        ${state === "undiscovered"
          ? sql`and not exists (select 1 from fg_species_region r where r.ktsn = s.ktsn and r.${sql(col)} = ${code})`
          : sql`and exists (select 1 from fg_species_region r where r.ktsn = s.ktsn and r.${sql(col)} = ${code}
                            and ${state === "found" ? sql`r.maxyear >= ${CUTOFF}` : sql`coalesce(r.maxyear,0) < ${CUTOFF}`})`}
      order by (coalesce(s.endangered_grade,'') <> '') desc, s.national_redlist_category, s.korean_name
      limit ${limit}`;
    return { region: code, region_name: region?.name ?? null, state, protected_default: isDefault, count: rows.length, species: rows };
  }
  const rows = await sql`
    select s.ktsn, s.korean_name, s.scientific_name, s.taxon_group, s.taxon_group_kor,
           s.endangered_grade, s.national_redlist_category, s.interest
    from fg_species s where 1=1 ${filt}
    order by (coalesce(s.endangered_grade,'') <> '') desc, s.national_redlist_category, s.korean_name
    limit ${limit}`;
  return { scope: "national", protected_default: isDefault, count: rows.length, species: rows };
}

async function taxaSummary() {
  const rows = await sql`
    select t.taxon_group, t.taxon_group_kor, t.n_species,
           coalesce(a.recorded,0)::int recorded, coalesce(a.found,0)::int found
    from fg_taxa t
    left join (
      select taxon_group, count(*) recorded, count(*) filter (where my >= ${CUTOFF}) found
      from (select taxon_group, ktsn, max(maxyear) my from fg_species_region group by taxon_group, ktsn) g
      group by taxon_group) a on a.taxon_group = t.taxon_group
    order by t.n_species desc`;
  return {
    reference_year: CUTOFF + 10,
    taxa: rows.map((r: Record<string, number | string>) => ({
      ...r, dormant: (r.recorded as number) - (r.found as number),
      undiscovered: (r.n_species as number) - (r.recorded as number),
    })),
  };
}

const TOOLS: Record<string, (a: Record<string, unknown>) => Promise<unknown>> = {
  find_region: findRegion,
  region_discovery_summary: regionDiscoverySummary,
  undiscovered_priority_species: undiscoveredPrioritySpecies,
  search_species: searchSpecies,
  species_detail: speciesDetail,
  list_protected_species: listProtectedSpecies,
  taxa_summary: taxaSummary,
};

// Gemini functionDeclarations — 도구 이름·인자 스키마.
const DECLARATIONS = [
  { name: "find_region", description: "지역 이름으로 행정구역 코드를 찾는다(다른 도구의 region 인자용). 지역을 다룰 땐 먼저 호출.",
    parameters: { type: "OBJECT", properties: { name: { type: "STRING", description: "시도·시군구 이름 일부(예: 종로구, 강원)" } }, required: ["name"] } },
  { name: "region_discovery_summary", description: "지역의 발견/휴면/미발견 종 수 요약.",
    parameters: { type: "OBJECT", properties: { region: { type: "STRING", description: "시도 2자리 또는 시군구 5자리 코드" }, taxon_group: { type: "STRING", description: "분류군 코드(선택)" } }, required: ["region"] } },
  { name: "undiscovered_priority_species", description: "지역에서 아직 발견되지 않았지만 관심도 높은 종(발견공백 우선순위).",
    parameters: { type: "OBJECT", properties: { region: { type: "STRING" }, taxon_group: { type: "STRING" }, endangered_grade: { type: "STRING", description: "멸종위기 등급 I/II(선택)" }, redlist_category: { type: "STRING", description: "국가적색목록 CR/EN/VU/NT/LC/DD(선택, 쉼표 다중)" }, limit: { type: "INTEGER" } }, required: ["region"] } },
  { name: "search_species", description: "국명·학명으로 종을 검색해 ktsn 을 찾는다.",
    parameters: { type: "OBJECT", properties: { query: { type: "STRING" }, limit: { type: "INTEGER" } }, required: ["query"] } },
  { name: "species_detail", description: "종의 전국 발견 상태(발견/휴면/미발견)와 기록 지역 수.",
    parameters: { type: "OBJECT", properties: { ktsn: { type: "STRING", description: "종 코드(search_species 결과)" } }, required: ["ktsn"] } },
  { name: "list_protected_species", description: "멸종위기종·국가적색목록 종 목록. region 지정 시 그 지역의 상태(state)로 필터.",
    parameters: { type: "OBJECT", properties: { region: { type: "STRING" }, endangered_grade: { type: "STRING" }, redlist_category: { type: "STRING" }, state: { type: "STRING", description: "undiscovered/found/dormant" }, taxon_group: { type: "STRING" }, limit: { type: "INTEGER" } } } },
  { name: "taxa_summary", description: "9개 분류군별 종수·전국 발견/휴면/미발견 요약.",
    parameters: { type: "OBJECT", properties: {} } },
];

const SYSTEM = `당신은 '발견공백 도우미'입니다. 한국의 생물종 '발견공백'(국가생물종목록에는 있으나 국내 조사자료에 관측 기록이 없거나 오래된 종)을 안내합니다.
- 반드시 제공된 도구로 조회한 사실만 답하고, 수치를 지어내지 마세요. 도구가 빈 결과를 주면 그대로 "기록 없음"으로 전하세요.
- 지역이 언급되면 먼저 find_region 으로 코드를 확인한 뒤 다른 도구에 그 코드를 넘기세요.
- 발견 정의: 발견=최근 10년 내 기록, 휴면=기록은 있으나 10년 이상 미보고, 미발견=관측 기록 0(=발견공백). 기준연도 ${CUTOFF + 10}.
- 답변은 한국어로 간결하게. 종은 국명(학명) 형식으로, 필요한 만큼만 나열하세요.
- 생물다양성·발견공백과 무관한 요청은 정중히 범위를 벗어난다고 안내하세요.`;

async function callGemini(contents: unknown[]) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), GEMINI_TIMEOUT_MS);
  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent`,
      {
        method: "POST", signal: ctrl.signal,
        headers: { "Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: SYSTEM }] },
          tools: [{ functionDeclarations: DECLARATIONS }],
          contents,
          generationConfig: { temperature: 0.3, maxOutputTokens: 1024 },
        }),
      },
    );
    if (!res.ok) throw new Error(`Gemini ${res.status}: ${(await res.text()).slice(0, 300)}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  if (!GEMINI_KEY) return json({ error: "서버에 GEMINI_API_KEY 가 설정되지 않았습니다." }, 503);

  // 인증: 로그인 필수.
  const authHeader = req.headers.get("Authorization") ?? "";
  const token = authHeader.replace(/^Bearer\s+/i, "");
  if (!token) return json({ error: "로그인이 필요합니다." }, 401);
  const supa = createClient(SUPABASE_URL, ANON_KEY, { auth: { persistSession: false } });
  const { data: { user } = { user: null } } = await supa.auth.getUser(token);
  if (!user) return json({ error: "로그인이 필요합니다." }, 401);

  // 요청 파싱.
  let body: { messages?: { role: string; content: string }[] };
  try { body = await req.json(); } catch { return json({ error: "잘못된 요청입니다." }, 400); }
  const history = (body.messages ?? []).filter((m) => m && typeof m.content === "string" && m.content.trim());
  if (!history.length || history[history.length - 1].role !== "user") return json({ error: "메시지가 필요합니다." }, 400);

  // 일일 한도: 원자적 증가(초과 시 반영 안 됨).
  let remaining: number;
  try {
    const cap = await sql`
      insert into chat_usage (user_id, day, count) values (${user.id}, current_date, 1)
      on conflict (user_id, day) do update set count = chat_usage.count + 1, updated_at = now()
      where chat_usage.count < ${DAILY_CAP}
      returning count`;
    if (!cap.length) return json({ error: `오늘 사용 한도(${DAILY_CAP}회)를 모두 사용했습니다. 내일 다시 이용해 주세요.`, remaining: 0 }, 429);
    remaining = DAILY_CAP - (cap[0].count as number);
  } catch (_e) {
    return json({ error: "일시적인 오류가 발생했습니다." }, 500);
  }

  // 대화 이력 → Gemini contents.
  const contents: unknown[] = history.slice(-MAX_HISTORY).map((m) => ({
    role: m.role === "assistant" ? "model" : "user",
    parts: [{ text: m.content }],
  }));

  const started = Date.now();
  try {
    const usedTools: string[] = [];
    for (let step = 0; step < MAX_STEPS; step++) {
      if (Date.now() - started > BUDGET_MS) break;
      const data = await callGemini(contents);
      const parts = data?.candidates?.[0]?.content?.parts ?? [];
      const calls = parts.filter((p: Record<string, unknown>) => p.functionCall);
      if (!calls.length) {
        const text = parts.filter((p: Record<string, unknown>) => p.text).map((p: Record<string, string>) => p.text).join("").trim();
        return json({ reply: text || "답변을 생성하지 못했습니다. 질문을 바꿔 다시 시도해 주세요.", remaining, used_tools: usedTools });
      }
      contents.push({ role: "model", parts });
      const responses = [];
      for (const p of calls) {
        const name = p.functionCall.name as string;
        const args = (p.functionCall.args ?? {}) as Record<string, unknown>;
        usedTools.push(name);
        let result: unknown;
        try { result = TOOLS[name] ? await TOOLS[name](args) : { error: `알 수 없는 도구: ${name}` }; }
        catch (_e) { result = { error: "조회 중 오류가 발생했습니다." }; }
        responses.push({ functionResponse: { name, response: { result } } });
      }
      contents.push({ role: "user", parts: responses });
    }
    return json({ reply: "질문이 복잡해 한 번에 처리하지 못했습니다. 조금 더 구체적으로 나눠 물어봐 주세요.", remaining, used_tools: usedTools });
  } catch (e) {
    console.error("chat error:", e);
    return json({ error: "답변 생성 중 오류가 발생했습니다." }, 502);
  }
});
