// 발견공백 대화형 도우미 — Supabase Edge Function.
// 로그인 사용자의 질문을 Gemini(함수호출)로 처리하고, 도구는 fg_* 참조 테이블(DB 직결)만 조회한다.
// 배포: supabase functions deploy chat   ·   비밀키: supabase secrets set GEMINI_API_KEY=...
// 기본 주입 비밀(SUPABASE_URL/ANON_KEY/DB_URL)은 Supabase가 제공. 원시 좌표·개인정보는 노출하지 않는다.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import postgres from "https://deno.land/x/postgresjs@v3.4.5/mod.js";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const GEMINI_KEY = Deno.env.get("GEMINI_API_KEY") ?? "";
const MODEL = Deno.env.get("GEMINI_MODEL") ?? "gemini-flash-lite-latest";
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
const TAXA_CODES = new Set(["IN", "IV", "VP", "-P", "MS", "AV", "MM", "RP", "AM"]);
const TAXA_KOR: Record<string, string> = {
  "곤충": "IN", "곤충류": "IN", "무척추": "IV", "무척추동물": "IV", "관속식물": "VP", "식물": "VP",
  "어류": "-P", "물고기": "-P", "선태": "MS", "선태류": "MS", "이끼": "MS", "조류": "AV", "새": "AV",
  "포유류": "MM", "포유": "MM", "파충류": "RP", "파충": "RP", "양서류": "AM", "양서": "AM",
};
const resolveTaxon = (v: unknown): string | null => {
  const s = String(v ?? "").trim();
  if (!s) return null;
  if (TAXA_CODES.has(s.toUpperCase())) return s.toUpperCase();
  return TAXA_KOR[s] ?? TAXA_KOR[s.replace(/류$/, "")] ?? s;
};

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
  const tg = resolveTaxon(a.taxon_group);
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
  const tg = resolveTaxon(a.taxon_group);
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
  const tg = resolveTaxon(a.taxon_group);
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

const TAXON_RANK_COL: Record<string, string> = { class: "class_la", order: "order_la", family: "family_la", genus: "genus_la" };
const TAXON_RANK_KOR: Record<string, string> = { class: "강", order: "목", family: "과", genus: "속" };

async function listSpeciesByTaxon(a: Record<string, unknown>) {
  const rank = String(a.rank ?? "").trim().toLowerCase();
  const col = TAXON_RANK_COL[rank];
  if (!col) return { error: "rank 는 class(강)·order(목)·family(과)·genus(속) 중 하나여야 합니다." };
  const nameRaw = String(a.name ?? "").trim();
  if (!nameRaw) return { error: "분류명(강/목/과/속)이 필요합니다." };

  // 한글 분류명 → 라틴명 해석: family/genus 만 매핑 테이블이 있음(taxon_ko.js 는 사진 보유 종 범위라 일부만 커버).
  // class/order 는 한글 매핑 소스가 없어 입력값을 라틴명으로 간주(Gemini 가 스스로 학명으로 바꿔 넘기도록 시스템 프롬프트에서 안내).
  const ko = (rank === "family" || rank === "genus")
    ? (await sql`select latin from fg_taxon_name where rank = ${rank} and korean = ${nameRaw} limit 1`)[0]
    : undefined;
  const latin = ko?.latin ?? nameRaw;

  const code = String(a.region ?? "").trim();
  if (code && code.length !== 2 && code.length !== 5) return { error: "region 은 시도(2자리) 또는 시군구(5자리) 코드여야 합니다." };
  const rcol = code ? regionField(code) : "sido";
  const state = String(a.state ?? "").trim().toLowerCase();
  const limit = Math.max(1, Math.min(Number(a.limit ?? 30), 100));

  const rows = await sql`
    select s.ktsn, s.korean_name, s.scientific_name,
           s.class_la, s.order_la, s.family_la, s.genus_la,
           s.endangered_grade, s.national_redlist_category, s.interest, g.my
    from fg_species s
    left join (
      select ktsn, max(maxyear) my from fg_species_region
      ${code ? sql`where ${sql(rcol)} = ${code}` : sql``}
      group by ktsn) g on g.ktsn = s.ktsn
    where lower(s.${sql(col)}) = lower(${latin})
    order by s.korean_name
    limit ${limit}`;
  if (!rows.length) {
    return { error: `'${nameRaw}'(${TAXON_RANK_KOR[rank]})에 해당하는 종을 찾지 못했습니다. 라틴 학명으로 다시 시도해 보세요(예: family=Lucanidae, order=Coleoptera).` };
  }
  const withState = rows.map((r) => {
    const my = r.my as number | null;
    const st = !my ? "undiscovered" : my >= CUTOFF ? "found" : "dormant";
    const { my: _drop, ...rest } = r;
    return { ...rest, state: st };
  });
  const filtered = state ? withState.filter((r) => r.state === state) : withState;
  return { rank, name: nameRaw, latin, region: code || null, count: filtered.length, species: filtered };
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
  list_species_by_taxon: listSpeciesByTaxon,
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
  { name: "list_species_by_taxon", description: "특정 강(class)·목(order)·과(family)·속(genus)에 속한 종 목록과 발견 상태(발견/휴면/미발견). 과·속은 한글 분류명(예: 사슴벌레과)도 가능하지만, 강·목은 한글 매핑이 없으니 라틴 학명으로 넘길 것(모르면 학명으로 스스로 변환).",
    parameters: { type: "OBJECT", properties: {
      rank: { type: "STRING", description: "class(강)·order(목)·family(과)·genus(속) 중 하나" },
      name: { type: "STRING", description: "분류명 — family/genus는 한글(예: 사슴벌레과) 또는 라틴 가능, class/order는 라틴 학명(예: Coleoptera)만" },
      region: { type: "STRING", description: "시도 2자리 또는 시군구 5자리 코드(선택, 지역 한정 시 find_region 으로 먼저 코드 확인)" },
      state: { type: "STRING", description: "found/dormant/undiscovered 로 필터(선택)" },
      limit: { type: "INTEGER" },
    }, required: ["rank", "name"] } },
];

const SYSTEM = `당신은 '발견공백 도우미'입니다. 한국의 생물종 '발견공백'(국가생물종목록에는 있으나 국내 조사자료에 관측 기록이 없거나 오래된 종)을 안내합니다.
- 반드시 제공된 도구로 조회한 사실만 답하고, 수치를 지어내지 마세요. 도구가 빈 결과를 주면 그대로 "기록 없음"으로 전하세요.
- 도구는 꼭 필요한 것만 최소 횟수로 호출하세요. 같은 정보를 여러 도구로 중복 조회하지 말고, 답할 정보가 모이면 즉시 최종 답변을 작성하세요.
- 발견 정의: 발견=최근 10년 내 기록, 휴면=기록은 있으나 10년 이상 미보고, 미발견=관측 기록 0(=발견공백). 기준연도 ${CUTOFF + 10}.
- 답변은 한국어로 간결하게. 종은 국명(학명) 형식으로, 필요한 만큼만 나열하세요.
- 생물다양성·발견공백과 무관한 요청은 정중히 범위를 벗어난다고 안내하세요.

[도구 선택]
- 지역이 언급되면 먼저 find_region 으로 코드를 확인하고, 그 코드를 다른 도구의 region 인자로 넘기세요.
- 지역의 발견/휴면/미발견 '규모·현황' → region_discovery_summary.
- 지역에서 아직 못 찾은 종 '목록' → undiscovered_priority_species.
- 멸종위기·적색목록 종 목록 → list_protected_species (region+state 로 지역별 상태 필터).
- 특정 종의 전국 발견 상태 → search_species 로 ktsn 을 찾고 species_detail.
- 전국 분류군별 요약 → taxa_summary (특정 지역 질문에는 쓰지 마세요).
- 특정 강·목·과·속(예: 사슴벌레과, 하늘소과, 진달래속, 딱정벌레목)에 속한 종 목록·미발견 종 → list_species_by_taxon (rank=class|order|family|genus). 과·속은 한글명을 그대로 넘겨도 되지만, 강·목은 한글 매핑이 없으니 당신이 아는 라틴 학명으로 바꿔서 넘기세요(예: 딱정벌레목→Coleoptera). taxon_group(9개 대분류: 곤충류 등)과는 다른 개념이니 혼동하지 마세요. KTSN 분류체계는 강-목-과-속-종/아종까지만 있고 아과·족은 지원하지 않습니다 — 물어보면 그렇게 안내하세요.
- taxon_group 인자에는 코드를 넘기세요: IN=곤충류, IV=무척추동물(곤충제외), VP=관속식물, -P=어류, MS=선태류, AV=조류, MM=포유류, RP=파충류, AM=양서류.`;

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
    if (!res.ok) {
      const err = new Error(`Gemini ${res.status}: ${(await res.text()).slice(0, 300)}`) as Error & { status?: number };
      err.status = res.status;
      throw err;
    }
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
    let spHint: Record<string, string> | null = null;    // 지도 딥링크(종별 mode B)
    let regHint: Record<string, string> | null = null;   // 지도 딥링크(지역·분류군 mode A)
    for (let step = 0; step < MAX_STEPS; step++) {
      if (Date.now() - started > BUDGET_MS) break;
      const data = await callGemini(contents);
      const parts = data?.candidates?.[0]?.content?.parts ?? [];
      const calls = parts.filter((p: Record<string, unknown>) => p.functionCall);
      if (!calls.length) {
        const text = parts.filter((p: Record<string, unknown>) => p.text).map((p: Record<string, string>) => p.text).join("").trim();
        return json({ reply: text || "답변을 생성하지 못했습니다. 질문을 바꿔 다시 시도해 주세요.", remaining, used_tools: usedTools, map: spHint ?? regHint });
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
        // 지도 딥링크 힌트: 종 상세(mode B) 우선, 없으면 지역·분류군 choropleth(mode A)
        const r = result as Record<string, unknown>;
        if (r && !r.error) {
          if (name === "species_detail" && r.ktsn) {
            spHint = { mode: "B", sp: String(r.ktsn) };
          } else if (name === "region_discovery_summary" || name === "undiscovered_priority_species" || name === "list_protected_species") {
            const rc = String(args.region ?? "").trim();
            const tg = resolveTaxon(args.taxon_group);
            const h: Record<string, string> = { mode: "A", metric: "gap" };
            if (rc.length === 5) { h.sigungu = rc; h.sido = rc.slice(0, 2); }
            else if (rc.length === 2) h.sido = rc;
            if (tg && TAXA_CODES.has(tg)) h.taxon = tg;
            if (name === "list_protected_species" && String(args.state ?? "").toLowerCase() === "found") h.metric = "found";
            if (h.sido || h.taxon) regHint = h;
          }
        }
        responses.push({ functionResponse: { name, response: { result } } });
      }
      contents.push({ role: "user", parts: responses });
    }
    try { await sql`update chat_usage set count = greatest(count - 1, 0) where user_id = ${user.id} and day = current_date`; } catch (_e) { /* noop */ }
    return json({ reply: "질문이 복잡해 한 번에 처리하지 못했습니다. 조금 더 구체적으로 나눠 물어봐 주세요.", remaining: remaining + 1, used_tools: usedTools });
  } catch (e) {
    console.error("chat error:", e);
    try { await sql`update chat_usage set count = greatest(count - 1, 0) where user_id = ${user.id} and day = current_date`; } catch (_e) { /* noop */ }
    const rateLimited = (e as { status?: number })?.status === 429 || String(e).includes("Gemini 429");
    return json({
      error: rateLimited
        ? "지금 이용이 몰려 잠시 후 다시 시도해 주세요. (무료 사용량 분당 제한)"
        : "답변 생성 중 오류가 발생했습니다.",
      remaining: remaining + 1,
    }, rateLimited ? 429 : 502);
  }
});
