/* 라디오 데스크 — Firebase Cloud Messaging service worker
 *
 * Streamlit Community Cloud는 루트 정적 파일 서빙이 제한적입니다.
 * 커스텀 도메인·Nginx/Cloudflare 등에서 이 파일을 사이트 루트
 * `/firebase-messaging-sw.js` 로 제공하세요.
 *
 * Firebase 콘솔 → 프로젝트 설정 값으로 아래 firebaseConfig 를 채웁니다.
 */
/* eslint-disable no-undef */
importScripts("https://www.gstatic.com/firebasejs/10.14.0/firebase-app-compat.js");
importScripts(
  "https://www.gstatic.com/firebasejs/10.14.0/firebase-messaging-compat.js"
);

firebase.initializeApp({
  apiKey: "REPLACE_ME",
  authDomain: "REPLACE_ME.firebaseapp.com",
  projectId: "REPLACE_ME",
  messagingSenderId: "REPLACE_ME",
  appId: "REPLACE_ME",
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage(function (payload) {
  const title =
    (payload.notification && payload.notification.title) || "라디오 데스크 속보";
  const options = {
    body: (payload.notification && payload.notification.body) || "",
    data: payload.data || {},
  };
  self.registration.showNotification(title, options);
});
