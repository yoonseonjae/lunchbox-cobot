# 나만의 도련님 도시락 — 키오스크 프로젝트

Figma Make로 디자인된 도시락 주문 키오스크 웹 애플리케이션입니다.  
로봇 서빙 연동을 포함한 주문 흐름(광고 → 선호도 → 메뉴 선택 → 확인 → 수령)을 제공합니다.

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| 프레임워크 | React 18 + TypeScript |
| 빌드 도구 | Vite 6 |
| 스타일링 | Tailwind CSS v4 |
| UI 컴포넌트 | shadcn/ui (Radix UI 기반) |
| 상태 관리 | React Hooks (useState, useEffect) |
| 백엔드/DB | Firebase Firestore + Realtime Database |
| 아이콘 | Lucide React, MUI Icons |
| 애니메이션 | Motion (Framer Motion) |
| 패키지 매니저 | pnpm |

---

## 환경 요구사항

| 항목 | 버전 |
|------|------|
| Node.js | **18.x 이상** 권장 |
| pnpm | **8.x 이상** |
| 브라우저 | Chrome / Edge 최신 버전 권장 (키오스크 환경) |

> pnpm이 없다면 먼저 설치하세요:
> ```bash
> npm install -g pnpm
> ```

---

## 주요 의존성

### 프로덕션 의존성
- **React 18** — UI 렌더링
- **react-router 7** — SPA 라우팅
- **Firebase** — Firestore(주문 데이터), Realtime Database(로봇 상태)
- **@radix-ui/*** — 접근성 기반 헤드리스 UI 컴포넌트
- **@mui/material + @emotion*** — MUI 컴포넌트 (일부 사용)
- **tailwind-merge / clsx / class-variance-authority** — 동적 클래스 유틸리티
- **lucide-react** — 아이콘
- **react-hook-form** — 폼 상태 관리
- **recharts** — 차트
- **sonner** — 토스트 알림
- **motion** — 애니메이션
- **react-dnd / react-dnd-html5-backend** — 드래그 앤 드롭

### 개발 의존성
- **Vite 6** — 개발 서버 및 빌드
- **@vitejs/plugin-react** — React Fast Refresh
- **@tailwindcss/vite** — Tailwind CSS v4 Vite 플러그인
- **TypeScript** — 타입 검사

---

## 설치 및 실행 방법

### 1. 저장소 클론 (또는 폴더 공유 시 해당 디렉토리로 이동)

```bash
cd kiosk_project/figma
```

### 2. 의존성 설치

```bash
pnpm install
```

> npm을 사용하는 경우:
> ```bash
> npm install
> ```

### 3. 개발 서버 실행

```bash
pnpm dev
```

브라우저에서 `http://localhost:5173` 접속

### 4. 프로덕션 빌드

```bash
pnpm build
```

빌드 결과물은 `figma/dist/` 폴더에 생성됩니다.

### 5. 빌드 결과 미리보기

```bash
pnpm preview
```

---

## Firebase 배포 (선택 사항)

프로젝트 루트(`kiosk_project/`)에서 실행합니다.

```bash
# Firebase CLI 설치 (최초 1회)
npm install -g firebase-tools

# Firebase 로그인
firebase login

# 빌드 후 배포
cd figma && pnpm build && cd ..
firebase deploy --only hosting
```

> `firebase.json`의 `public` 경로가 `figma/dist`로 설정되어 있습니다.

---

## 프로젝트 구조

```
kiosk_project/
├── firebase.json          # Firebase Hosting 설정
├── .firebaserc            # Firebase 프로젝트 연결
├── .gitignore
└── figma/                 # 프론트엔드 소스
    ├── package.json
    ├── vite.config.ts
    ├── src/
    │   ├── main.tsx
    │   ├── app/
    │   │   ├── App.tsx            # 메인 앱 (주문 흐름 제어)
    │   │   ├── components/
    │   │   │   ├── MenuCard.tsx
    │   │   │   ├── OrderSummary.tsx
    │   │   │   ├── CircularProgress.tsx
    │   │   │   └── ui/
    │   │   │       ├── StepAd.tsx          # 광고 화면
    │   │   │       ├── StepPreference.tsx  # 선호도 선택
    │   │   │       ├── StepMenuSelection.tsx # 메뉴 선택
    │   │   │       ├── StepConfirmation.tsx  # 주문 확인
    │   │   │       └── StepPickup.tsx       # 수령 화면
    │   │   ├── hooks/
    │   │   │   └── useOrder.ts    # 주문 상태 훅
    │   │   └── lib/
    │   │       └── firebase.ts    # Firebase 초기화 및 함수
    │   └── styles/
    └── dist/              # 빌드 출력 (git 제외)
```

---

## 원본 Figma 디자인

[나만의 도련님 도시락 (Figma)](https://www.figma.com/design/GHyOG9l1pMoHP6nue4LkoZ/%EB%82%98%EB%A7%8C%EC%9D%98---%EB%8F%84%EB%A0%A8%EB%8B%98--%EB%8F%84%EC%8B%9C%EB%9D%BD--%EB%B3%B5%EC%82%AC-)
