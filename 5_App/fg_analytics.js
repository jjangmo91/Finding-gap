// GA4 게이트 로더 — window.GA4_ID(config.js 주입)가 있을 때만 gtag 로드. 없으면 무해 no-op(네트워크 0).
// 배포: build_dist.py 가 .env 의 GA4_MEASUREMENT_ID 를 config.js 의 window.GA4_ID 로 기록.
// 사용: 어디서든 window.fgTrack('event_name', {params}) — ID 없으면 조용히 무시.
(function () {
  window.fgTrack = window.fgTrack || function () {};   // 기본 no-op — ID 없거나 로드 전 호출도 안전
  var id = window.GA4_ID;
  if (!id) return;                                     // 측정 ID 없으면 gtag 미로드(요청 0·쿠키 0)
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  function gtag() { dataLayer.push(arguments); }
  window.gtag = gtag;
  gtag('js', new Date());
  gtag('config', id, { anonymize_ip: true });          // IP 익명화(개인정보 최소화)
  window.fgTrack = function (name, params) {
    try { gtag('event', name, params || {}); } catch (e) {}
  };
})();
