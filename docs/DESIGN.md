# KEL 설계 문서 (DESIGN.md)

> **상태: v0.2** · 2026-10-22 · Phase 0 결정 확정
>
> 사용자가 결정을 위임해("다 너가 정해") 이 문서의 추천안을 모두 확정했다. 결정 상태의
> 기준은 [DECISIONS.md](DECISIONS.md)다. 이후 바뀌는 결정은 DECISIONS.md에 먼저 기록한다.
> 근거 자료(측정값과 출처):
> [작업 환경 측정](research/2026-10-22-environment.md) ·
> [업스트림 조사](research/2026-10-22-upstream-survey.md) ·
> [apk v3 사전 검증](research/2026-10-22-apk-v3-poc.md)

KEL(Kelp Enterprise Linux, os-release `ID=kel`)은 다른 배포판을 베이스로 쓰지 않는
독립 배포판이다. 커널, 툴체인, libc부터 모든 것을 업스트림 소스에서 KEL 자체 빌드
시스템으로 빌드하고, 레시피만으로 언제든 처음부터 다시 만들 수 있게 한다. 지향점은
엔터프라이즈 서버급 안정성(긴 지원 기간, 보안 업데이트, 서명된 패키지, 재현 가능한
빌드)이고, 규모는 1인 개발 + AI, 빌드 팜 없음이다.

## 0. 결정 요약

| 항목 | 결정 | 핵심 근거 |
|---|---|---|
| 아키텍처 (D-001) | x86_64 먼저(Phase 1~3), aarch64는 같은 레시피로 크로스 빌드. 기준선 x86-64-v2 / ARMv8.0-A | 호스트가 x86_64이고 KVM 없음. Proxmox VE 새 VM 기본 CPU가 v2 계열 |
| 패키지 형식·매니저 (D-002) | **apk-tools 3(v3 형식) 채택**, 직접 개발하지 않음 | 의존성 최소(4.5초 빌드), Chimera·OpenWrt 운영 실적, 서명·설치·변조 거부를 직접 확인 |
| 빌드 시스템 (D-003) | 자체 `kel` 도구 + TOML 레시피 + bubblewrap 격리 | 메타데이터를 실행 없이 파싱, 비특권·네트워크 차단 빌드 확인 |
| libc (D-004) | glibc | 엔터프라이즈 소프트웨어 호환, systemd의 1차 대상 |
| 컴파일러 (D-005) | GCC + binutils (LLVM은 필요할 때 일반 패키지로) | glibc·커널의 1차 대상, GCC 브랜치 수명 약 3.5년 |
| init (D-006) | systemd | 엔터프라이즈 표준, 통합 도구, 업스트림 안정 브랜치 |
| 유저랜드 (D-007) | GNU coreutils 등 + `/usr` 병합 + `bin`/`sbin` 병합 | 스크립트 호환, systemd 요구사항 |
| 부트로더 (D-008) | UEFI 전용, systemd-boot + 서명된 UKI, dracut-ng. Secure Boot는 자체 키로 시작, shim은 나중 | 가장 짧은 부팅 체인. shim 리뷰에는 법인·EV 인증서 등이 필요 |
| 설치 프로그램 (D-009) | systemd-sysinstall 평가 후 필요하면 소형 `kel install`, 무인 설치는 TOML 응답 파일 | 업스트림 부품 재사용으로 유지할 코드 최소화 |
| 업데이트 (D-010) | 패키지 단위. 이미지 기반은 같은 패키지로 만드는 변형판으로 나중에 | 추가 인프라 최소, CVE를 패키지 하나씩 처리 |
| 자체 도구 언어 (D-011) | Python 3, 표준 라이브러리만 | systemd·glibc 빌드에 어차피 필요해서 부트스트랩 비용 0 |
| 커널 정책 (D-012) | kernel.org 최신 LTS 추적, 메이저 안에서 다음 LTS로 리베이스, kABI 보장 안 함 | 업스트림 stable 팀의 백포트에 의존할 수밖에 없음 |
| 릴리스·지원·버전 (D-013) | 메이저 3년 주기, 메이저당 5년 지원(일반 3 + 보안 2), `major.minor`, 포인트 릴리스 6개월 | 5년 = Ubuntu LTS·RHEL 일반 지원·CRA 최소. 동시 안정 브랜치 2개로 제한 |
| 서명·신뢰 (D-014) | 오프라인 루트 키 + 온라인 저장소 서명 키, 개발 중에는 임시 키 | 키 유출 대비, 키 교체 가능 |
| 빌드 인프라 (D-015) | 개발은 이 세션, 무거운/정기 빌드와 aarch64는 GitHub Actions(공개 저장소 무료), 서명은 CI 밖 | 빌드 팜 없이 aarch64 네이티브 빌드 가능 |
| 라이선스·소스 공개 (D-016) | 레시피에 SPDX 필수, 바이너리 옆에 대응 소스, KEL 자체 코드는 MIT | GPL 등 업스트림 라이선스 준수 |
| 보안 기반 (D-017) | SELinux(refpolicy 기반 targeted), 패키지별 SPDX 3.0.1 SBOM, OSV + secdb 공지 | RHEL·SLE 16의 흐름, 기존 스캐너 호환 |

## 1. 목표와 비목표

### 목표

1. **독립 배포판.** 다른 배포판을 베이스로 쓰지 않는다. 커널, 툴체인, libc를 포함한
   모든 패키지를 업스트림 소스에서 KEL 빌드 시스템으로 빌드한다.
2. **언제든 처음부터 다시 빌드.** 저장소의 레시피와 업스트림 소스(체크섬, 가능하면 서명
   검증)만 있으면 명령 하나로 부트스트랩부터 저장소 생성까지 다시 할 수 있다.
3. **엔터프라이즈 서버 지향.** 안정된 ABI, 서명된 패키지, 보안 업데이트, 긴 지원 기간,
   재현 가능한 빌드, SBOM.
4. **1인 + AI로 유지 가능한 범위.** 모든 결정은 "한 사람이 몇 년 동안 유지할 수 있는가"를
   기준으로 한다.

### 비목표 (적어도 1.0까지)

- 데스크톱/GUI, 32비트 아키텍처, 오디오/그래픽 스택
- RHEL 등 다른 배포판과의 바이너리 호환, kABI(커널 모듈 ABI) 보장
- 독점 드라이버 동봉
- 패키지 수 경쟁: 1.0의 목표는 "작고 잘 관리되는 서버 코어"다 (대략 300~500개 소스 패키지)

## 2. 제약 조건과 작업 환경

자세한 측정값과 방법은 [research/2026-10-22-environment.md](research/2026-10-22-environment.md).

| 항목 | 측정값 | 설계에 주는 영향 |
|---|---|---|
| CPU | x86_64 4 vCPU (Xeon 2.1GHz) | x86_64를 먼저 한다. 1 SBU = 217초(코어 1개), GCC 전체 빌드+테스트 약 2.8시간 추정 |
| 메모리 | 15 GiB, 스왑 없음 | `-j4` 병렬 빌드는 충분. LLVM 같은 대형 C++ 링크는 주의 |
| 디스크 | 여유 약 31 GB | 큰 패키지는 하나씩 빌드하고 바로 정리. 산출물 장기 보관은 외부에 |
| 가상화 | KVM 없음 (TCG만) | 부팅 테스트는 가능(x86_64 UEFI 8.6초, aarch64 UEFI 16.3초). 에뮬레이션 빌드는 불가 |
| 격리 | 비특권 user namespace 동작 | bubblewrap 기반 격리 빌드 가능 |
| 네트워크 | 프록시 경유, kernel.org 약 25 MB/s, 일부 호스트 느림/차단 | 소스 캐시를 두고, 레시피에 대체 미러를 적는다 |
| 세션 | 임시 컨테이너, 비활성 시 회수 | git에 없는 것은 사라진다 → 레시피가 유일한 진실, 산출물 보관소 필요 |
| 저장소 | GitHub `jgchoimd-web/KEL`, **public** | 레시피 공개는 목표와 맞음. 바이너리 공개 배포는 별도 확인 후 |

## 3. 설계 원칙

1. **레시피가 진실의 원천이다.** 빌드 결과물은 언제든 버리고 다시 만들 수 있는
   캐시다. 손으로 고친 바이너리나 "한 번만 한 작업"은 없다.
2. **업스트림 우선.** 패치는 최소한으로 하고, 패치마다 이유와 업스트림 상태를 적는다.
3. **작게 시작해서 넓힌다.** 서버 코어부터. 패키지 하나를 추가할 때마다 유지 비용이
   생긴다는 것을 전제로 한다.
4. **검증은 실행으로.** 각 단계는 자동 테스트(빌드, 설치, 부팅)를 통과해야 끝난다.
5. **사람과 AI가 같이 읽고 고치기 쉬운 형식.** 선언적 메타데이터(파싱 가능) +
   짧은 셸 빌드 단계. 숨은 규칙보다 명시적인 설정.
6. **호스트 오염 금지.** 호스트 바이너리는 부트스트랩 출발점일 뿐이다. 최종 패키지에
   호스트 흔적이 없는지 자동으로 검사한다.
7. **비밀은 저장소 밖에.** 개인 키는 커밋하지 않는다(`.gitignore`로 1차 차단).
   공개 키만 `keys/`에 둔다.
8. **되돌리기 어려운 작업은 먼저 묻는다.** 공개 배포, 외부 저장소 푸시, 키 공개 등.

## 4. 항목별 설계

각 항목은 추천안, 대안 비교, 근거 순서로 적는다. 괄호 안 D-번호는 [DECISIONS.md](DECISIONS.md)의 항목이다.

### 4.1 아키텍처 우선순위와 ISA 기준선 — D-001

**추천: x86_64 먼저(Phase 1~3), aarch64는 같은 레시피의 크로스 빌드로 Phase 2 후반부터.
기준선은 x86-64-v2 / ARMv8.0-A.**

- 작업 호스트가 x86_64이고 KVM이 없어서, aarch64를 에뮬레이션으로 빌드하는 것은
  비현실적이다. 대신 레시피를 처음부터 크로스 빌드 가능하게 만들어 aarch64를 나중에
  "추가 작업"이 아니라 "같은 레시피의 다른 타깃"으로 만든다.
- 타깃 triplet: `x86_64-kel-linux-gnu`, `aarch64-kel-linux-gnu`
  (binutils `config.sub`가 `kel` vendor를 받아들이는 것을 확인함).

| 기준선 | 장점 | 단점 | 쓰는 곳 |
|---|---|---|---|
| **x86-64-v2** (추천) | 2009년 이후 거의 모든 x86 서버/VM에서 부팅. Proxmox VE의 새 VM 기본 CPU(`x86-64-v2-AES`)에서도 그대로 동작 | AVX2 최적화를 기본으로 못 씀 | SLES 16, Amazon Linux 2023 |
| x86-64-v3 | AVX2/BMI2/FMA로 성능 이득 | Haswell(2013) 이전 CPU와 보수적인 가상 CPU 모델에서 부팅 불가 | RHEL 10 (AlmaLinux는 v2 빌드를 따로 냄) |
| v2 기본 + v3 추가 | 호환성 + 성능. 방식은 두 가지: glibc-hwcaps로 일부 라이브러리만 v3판을 추가하거나, 패키지 세트 전체를 v3 변형으로 따로 빌드 | 빌드 시간·저장 공간 증가 | Ubuntu 26.04(선택형 amd64v3 변형), AlmaLinux 10(반대로 v3 기본 + v2 빌드) |

| aarch64 기준선 | 장점 | 단점 | 쓰는 곳 |
|---|---|---|---|
| **ARMv8.0-A** (추천) | 가장 넓은 호환성 | LSE 원자 연산 등 최신 기능은 런타임 감지에 의존 | RHEL 10, SLES 16 |
| ARMv8.2-A | 성능 | 오래된 보드/서버 제외 | Amazon Linux 2023 |

테스트 메모: QEMU TCG 기본 CPU(`qemu64`)는 v1 기능만 보여 주므로 v2 기준선
테스트도 `-cpu max`(v3까지 지원 확인) 같은 모델을 명시해야 한다.

### 4.2 패키지 형식과 매니저 — D-002

**추천: 직접 개발하지 않고 apk-tools 3(v3 패키지·색인 형식)을 채택한다.**
KEL의 차별점은 패키지 매니저가 아니라 빌드 재현성, 서명, 보안 대응, 지원 정책이다.
보안의 핵심인 패키지 매니저를 1인이 새로 만들고 유지하는 위험이 이득보다 크다.

| 선택지 | 장점 | 단점 |
|---|---|---|
| **apk-tools 3, v3 형식** (추천) | C로 작고 의존성이 zlib + OpenSSL(또는 mbedTLS) + 선택적 zstd뿐이라 부트스트랩 초기에 바로 빌드된다(**이 호스트에서 4.5초에 빌드 확인**). v3 형식은 Chimera(독립 배포판)와 OpenWrt 25.12가 실제로 운영 중. 색인과 패키지 모두 서명(RSA/ECDSA PEM 키). 빠르고 단순하며 `world` 파일로 시스템 상태를 선언적으로 관리. 서명 전 패키지가 바이트 단위로 재현됨(실측) | v3 형식 문서가 얇고 C 구조체 배치에 얽혀 있어 패키지는 apk 자체 명령(`mkpkg`/`mkndx`)으로만 만든다. 롤백 없음. 저장소 메타데이터 유효기간(freeze/replay 방어) 없음. **SELinux 라벨링 기능 없음**(소스 확인). 엔터프라이즈 관리자에게 낯설다. Alpine 본가는 아직 v2 형식 |
| RPM 6 + tdnf(또는 dnf5) | 엔터프라이즈 표준. 서명 검사 기본 강제, 패키지당 여러 서명(키 교체에 유리), PKCS#11 토큰 서명(6.1), SELinux 라벨링 플러그인, dnf5 history 롤백. Azure Linux 4.0·Photon OS가 독립적으로 채택 | 부트스트랩이 가장 무겁다. rpm 6은 C++20·Lua·libarchive·sqlite 등이 필요하고, **서명 검증에 Rust(rpm-sequoia)가 필요**해서 패키지 매니저보다 LLVM+Rust를 먼저 빌드해야 한다(디스크 31GB 호스트에 큰 부담). spec 파일 체계가 KEL 자체 레시피와 겹친다 |
| pacman 7 | 단순, 7.1부터 패키지·DB 서명 기본 필수, 다운로더 샌드박스 | GnuPG 의존. makepkg/devtools의 clean chroot는 root와 systemd-nspawn이 필요 |
| dpkg + apt 3 | 성숙, sqv 검증, `Valid-Until`로 replay 방어 | Rust(sqv) 포함 의존성이 많고 Debian 정책·도구 체계가 무겁다. .deb 자체는 서명되지 않음 |
| xbps / opkg | 작다 | xbps는 색인 무서명, opkg는 서명 검사가 기본으로 꺼져 있음 |
| 직접 개발 | TUF·Ed25519·SBOM을 처음부터 넣을 수 있다 | 의존성 풀이, 파일 충돌, 트리거, 자기 자신 업그레이드, 중단 복구 같은 어려운 문제를 1인이 다시 풀고 보안 검토까지 해야 한다 |

apk를 고르면 KEL이 직접 채워야 할 빈칸과 계획:

| 빈칸 | 대응 | 시기 |
|---|---|---|
| 저장소 신선도(freeze/replay) | TUF의 timestamp 역할처럼 짧은 유효기간을 가진 서명 파일을 저장소에 두고 `kel` 업데이트 도구가 검사. 장기적으로 apk 업스트림 기능 제안 검토 | Phase 4 |
| SELinux 라벨 | apk post-commit 훅으로 바뀐 파일에 `restorecon`. 업스트림에 라벨링 기능 제안 검토 | Phase 4 |
| 롤백 | Btrfs 스냅샷 연동 또는 이미지 변형판(4.10) | Phase 4 이후 |
| 서명 키 알고리즘 | RSA-4096(Alpine·Wolfi, 서명이 결정적) vs ECDSA P-256(OpenWrt, 작음) | Phase 2 |

### 4.3 빌드 시스템 (레시피 형식, 격리 빌드) — D-003

**추천: KEL 자체 빌드 도구 `kel`(Python, 4.11) + TOML 레시피(선언적 메타데이터 + 짧은
셸 빌드 단계) + bubblewrap 격리(root 불필요, 네트워크 차단, 선언된 의존성만 든 새 빌드 루트).**
구조는 같은 조합(Python + bwrap + apk v3)으로 독립 배포판을 빌드하는 Chimera cbuild와,
패키지마다 SBOM을 만드는 Wolfi melange를 참고한다.

| 선택지 | 장점 | 단점 |
|---|---|---|
| **자체 `kel` + TOML + bwrap** (추천) | "KEL 자체 빌드 시스템" 요구와 일치. 메타데이터를 코드 실행 없이 읽을 수 있어 SBOM·CVE 매칭·의존성 그래프에 바로 쓴다. 필요한 기능만 만든다 | 직접 만들고 유지해야 함 |
| cbuild 포크 (BSD-2) | 검증된 구조, 크로스 빌드, root 거부 | Chimera 전제(musl, LLVM, BSD 유저랜드, Python 템플릿)가 깊게 박혀 있음 |
| melange 채택 (Apache-2.0) | SBOM 내장, bwrap 러너 | Go 부트스트랩 필요, apk **v2** 형식 출력, 크로스 빌드 대신 QEMU 에뮬레이션 |
| abuild / APKBUILD | apk와 짝 | 셸 레시피라 정적 분석이 어렵고 Alpine 관례에 묶임 |
| Yocto/BitBake, Buildroot | 크로스 빌드에 강함 | 임베디드 이미지 지향, 패키지 저장소 운영형 배포판과 맞지 않음 |
| Nix / Guix | 재현성·롤백 최고 | 완전히 다른 OS 모델 |

레시피 예시 (형식은 Phase 1에서 확정, 값은 이번에 실제로 검증한 binutils 2.47):

```toml
[package]
name = "binutils"
version = "2.47"
revision = 0                       # 패키지 버전 binutils-2.47-r0
summary = "GNU assembler, linker and binary utilities"
license = "GPL-3.0-or-later"       # SPDX, 없으면 빌드 실패
homepage = "https://www.gnu.org/software/binutils/"

[[source]]
url = "https://sourceware.org/pub/binutils/releases/binutils-2.47.tar.xz"
sha256 = "154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff"
signature = "https://sourceware.org/pub/binutils/releases/binutils-2.47.tar.xz.sig"
signing_keys = ["3A24BC1E8FB409FA9F14371813FCEF89DD9E3C4F"]   # 지문 고정

[build]
style = "gnu-configure"            # gnu-configure | meson | cmake | custom
out_of_tree = true
build_depends = ["base-devel"]
configure_args = ["--disable-nls", "--disable-werror",
                  "--enable-new-dtags", "--enable-default-hash-style=gnu"]
check = true                       # 크로스 빌드에서는 자동으로 건너뜀

[subpackages.dev]
files = ["usr/include", "usr/lib/*.a"]
```

격리 빌드 규칙(제안):
- 빌드마다 새 루트: 레시피에 선언된 빌드 의존성 패키지만 apk로 설치한다
  (부트스트랩 stage 1~2에서는 stage 디렉터리를 쓴다).
- 소스는 빌드 전에 받아 체크섬·서명을 검증하고 읽기 전용으로 붙인다. 빌드 중에는
  `bwrap --unshare-all`로 네트워크가 없다.
- `kel`은 root로 실행하기를 거부하고, 샌드박스 안에서만 uid 0으로 매핑한다
  (bubblewrap 0.12부터 setuid 지원이 없어져 비특권 user namespace가 필수인데, 이 호스트에서 동작 확인).
- 고정 환경: `SOURCE_DATE_EPOCH`, `TZ=UTC`, `LC_ALL=C.UTF-8`, `umask 022`, 고정 빌드 경로.
- 단계: fetch(샌드박스 밖) → prepare(풀기·패치) → configure → build → check → install(DESTDIR)
  → 후처리(strip과 디버그 정보 분리, 권한 정규화, ELF/호스트 흔적 검사, 공유 라이브러리
  의존성 자동 계산, 라이선스 파일 확인) → `apk mkpkg` → SBOM.
- 크로스 빌드는 처음부터 지원한다(`--arch aarch64`). 테스트(`check`)는 네이티브 빌드에서만.

**구현하면서 정해진 규칙 (Phase 1, `tools/kel`)**

| 주제 | 규칙 | 이유 |
|---|---|---|
| 샌드박스 모드 | `host`: 호스트 `/`를 읽기 전용으로 보고 작업 디렉터리만 쓰기 가능(stage 1~2, host-tools). `sysroot`: sysroot를 `/`로 삼고 호스트는 전혀 안 보임(stage 3부터) | 호스트 도구가 필요한 단계와 그렇지 않은 단계를 구분 |
| `/bin/sh` | host 모드 샌드박스 안에서만 bash를 `/bin/sh`로 보이게 함 | Ubuntu의 `/bin/sh`는 dash, 빌드 시스템은 bash를 전제로 하는 경우가 많음 |
| 파일 소유자 | `apk mkpkg`를 user namespace 안에서 uid 0으로 실행 | apk v3는 소유자를 이름으로 기록하고, 이름은 루트의 `/etc/passwd`에서 찾음. 호스트 사용자 이름이 패키지에 들어가는 것을 막음 |
| 패키지 파일은 모두 root 소유 | 비특권 샌드박스는 uid/gid 하나만 매핑하므로 패키지 안의 파일은 전부 `root:root`다. root가 아닌 소유자가 필요한 것(사용자, `/var` 아래 상태 디렉터리, `/var/log/wtmp` 같은 파일)은 패키지가 `sysusers.d`와 `tmpfiles.d` 설정을 싣고 설치 때와 부팅 때 systemd가 만든다. setuid root는 모드로 표현할 수 있어 그대로 둔다 | subuid 범위와 setuid 도우미(`newuidmap`)가 없는 빌드 호스트(CI 포함)에서도 같은 결과. systemd 배포판의 일반적인 방식이고, 나중의 이미지 기반 변형판(`/usr`만 담은 이미지)과도 맞음 |
| `so:` 의존성 | ELF의 `DT_SONAME`은 `so:<soname>=<파일 이름의 버전>`으로 provides, `DT_NEEDED`는 `so:<name>`으로 depends | apk는 버전 없는 provides를 자동 선택하지 않음(apk-package(5)) |
| 서브패키지 | `-dev`, `-doc` 등은 같은 버전의 본 패키지에 의존(`<이름>=<버전>-r<리비전>`) | `-dev`의 `.so` 링크는 본 패키지의 라이브러리를 가리킴 |
| merged `/usr` | 빌드의 마지막 단계에서 `bin`, `sbin`, `usr/sbin`을 `usr/bin`으로, `lib`, `lib64`, `usr/lib64`를 `usr/lib`로 옮김. 이 경로는 정해진 심볼릭 링크(`bin → usr/bin` 등, `filesystem` 패키지가 싣는다)로만 허용하고 디렉터리면 정책 위반 | DESIGN 4.7 |
| 비어 있어야 하는 경로 | `/usr/local`, `/opt`, `/tmp`, `/var/tmp`, `/run`, `/home`, `/root`, `/dev`, `/proc`, `/sys`, `/mnt`, `/media`, `/srv`에는 빈 디렉터리만 실을 수 있음. `/tools`와 `/kel`(부트스트랩·빌드 위치)은 아예 금지 | 실행 중에 채워지거나 관리자 몫인 경로. 빌드 환경이 패키지에 새는 것을 막음 |
| 개발용 서명 키 | `work/keys/`에 RSA-4096 생성(공개 키는 `work/keys/trusted/`), git에 넣지 않음 | D-014, D-019 |
| 부트스트랩 패키징 | stage 3에서는 호스트용 apk(host-tools 단계)로 패키지를 만들고 내용을 빌드 루트에 복사 | KEL의 apk가 빌드되기 전까지의 임시 방법. stage 4부터 KEL의 apk 사용 |

### 4.4 libc — D-004

**추천: glibc.** (현재 2.44, 6개월 주기, release 브랜치 백포트 유지)

| 선택지 | 장점 | 단점 |
|---|---|---|
| **glibc** (추천) | 엔터프라이즈 소프트웨어(상용 DB, 모니터링 에이전트, 드라이버 도구)가 사실상 glibc만 지원. 심볼 버전으로 장기 ABI 호환. systemd의 기본 대상. release 브랜치에 업스트림이 직접 보안 수정 백포트 | 코드가 크고 복잡. 정적 링크가 불편. 포인트 릴리스 tarball이 없어 브랜치 추적 필요 |
| musl (1.2.6) | 작고 단순, 정적 링크에 좋음, MIT | glibc 대상 바이너리와 호환성 문제, 릴리스 주기 불규칙(1.2.5→1.2.6 2년), 상용 소프트웨어 지원 거의 없음 |

엔터프라이즈 서버라는 목표에서는 "다른 회사가 만든 바이너리가 그냥 돈다"가 결정적이다.

### 4.5 컴파일러와 툴체인 — D-005

**추천: GCC + GNU binutils를 시스템 툴체인으로. LLVM/Clang은 필요할 때 일반 패키지로.**

| 선택지 | 장점 | 단점 |
|---|---|---|
| **GCC + binutils** (추천) | glibc·커널의 1차 대상, 주요 엔터프라이즈 배포판 모두 사용. 브랜치 수명 약 3.5년(유지보수 백포트 무료) | GCC 15/16의 C23/C++20 기본값으로 오래된 패키지 수정 필요 |
| LLVM/Clang + lld | 크로스 컴파일 단일 바이너리, 빠른 링크 | 릴리스 라인마다 수정 약 4개월, LTS 없음. glibc의 Clang 빌드는 아직 실험적(2.43~) |

- 버전 기준(지금 시점 최신): GCC 16.2, binutils 2.47, glibc 2.44. 1.0 동결 시점에 다시 정한다.
- KEL 메이저 릴리스 하나에는 GCC 메이저 하나를 고정한다.
- 링커는 ld.bfd (gold는 binutils 2.44부터 deprecated, 2.47에는 없음).
- 보안 강화 기본 플래그(PIE, `-fstack-protector-strong`, `_FORTIFY_SOURCE=3`,
  `-fstack-clash-protection`, `-fcf-protection`(x86_64), RELRO/now 등)는 Phase 2에서
  레시피 공통 설정으로 정하고 검사 도구로 확인한다.

### 4.6 init — D-006

**추천: systemd** (현재 v262, 업스트림이 안정 브랜치 여러 개를 동시에 유지)

| 선택지 | 장점 | 단점 |
|---|---|---|
| **systemd** (추천) | 엔터프라이즈 관리자가 이미 아는 도구. journald·udev·networkd·timesyncd·logind·cgroup v2 자원 제어·서비스 샌드박스(`ProtectSystem=` 등)가 통합. 외부 소프트웨어가 unit 파일을 기본 제공. systemd-boot/ukify/repart 등 부팅·이미지 도구도 같은 곳에서 | 크고 변화가 빠르다(v258 cgroup v1 제거, v260 SysV 제거, v262 sysupdate 다시 실험적). glibc 사실상 필수(musl은 "불완전 지원") |
| OpenRC (0.64.1) | 성숙, 단순, Alpine/Gentoo 실적 | 로그·udev·네트워크를 따로 골라 유지. 소켓 활성화는 문서에서 확인하지 못함 |
| dinit (0.22.1) | 현대적 의존성 모델, cgroup 지원 | 아직 1.0 이전 베타 |
| s6 + s6-rc | 활발, readiness 기반 의존성 | 프런트엔드(s6-frontend 0.2)가 아주 새로움, 관리자 친숙도 낮음 |
| runit (2.3.1) | 최소 | 의존성·cgroup이 스크립트 관례에 의존 |

systemd를 고르면 따라오는 결정:
- **merged `/usr` 필수**(v255부터). `/usr/sbin`도 `/usr/bin`에 합친다(v256부터 분리 시
  `unmerged-bin` taint, Fedora 42도 합침). → `/bin`, `/sbin`, `/lib`, `/lib64`,
  `/usr/sbin`은 심볼릭 링크.
- 최소 커널 5.10(권장 5.14 이상) — LTS 6.18이면 문제없음.
- systemd 빌드에 meson, Python 3.9+, jinja2가 필요 → Python이 베이스 빌드 의존성이 된다
  (4.11 도구 언어 결정과 연결).
- 시간 동기화: timesyncd는 SNTP만 구현하므로 서버 기본은 **chrony**(4.9) 추천.

### 4.7 기본 유저랜드와 파일시스템 배치 — D-007

**추천: GNU 유저랜드(coreutils, findutils, grep, sed, gawk, tar, bash 등) + util-linux +
shadow + Linux-PAM. BusyBox는 쓰지 않거나 설치 이미지/구조용(rescue)으로만.**

| 선택지 | 장점 | 단점 |
|---|---|---|
| **GNU** (추천) | 스크립트 호환성 최고, 엔터프라이즈 표준 | 크기 |
| BusyBox (1.38.0) / toybox (0.8.15) | 작다, initramfs/컨테이너에 좋다 | GNU 확장 옵션 미지원, BusyBox 최신판이 업스트림 표기상 "unstable" |
| uutils (Rust, 0.12.0) | 메모리 안전 | Ubuntu 26.04 LTS조차 cp/mv/rm은 GNU 유지, 감사에서 113건/CVE 20건. 엔터프라이즈 기본값으로는 이르다 |

파일시스템 배치(제안):
- `/usr` 병합 + `bin`/`sbin` 병합, 라이브러리는 `/usr/lib` 하나(x86_64 ABI가 요구하는
  `/lib64/ld-linux-x86-64.so.2`는 심볼릭 링크로 제공).
- `/etc/os-release` → `../usr/lib/os-release` 상대 링크. 초안:
  ```
  NAME="KEL"
  ID=kel
  PRETTY_NAME="KEL 1.0 (Kelp Enterprise Linux)"
  VERSION_ID="1.0"
  HOME_URL="https://github.com/jgchoimd-web/KEL"
  SUPPORT_END=YYYY-MM-DD      # 지원 정책 확정 후
  CPE_NAME="cpe:/o:kel:kel:1.0"
  ```
- sudo 선택(sudo 1.9.17p2는 2025-07 이후 안정판 없음 vs sudo-rs 0.2.15는 Rust 필요)은
  Phase 3에서 정한다. Phase 1~2의 최소 시스템에는 필요 없다.

### 4.8 부트로더, initramfs, Secure Boot — D-008

**추천: x86_64·aarch64 모두 UEFI 전용. systemd-boot + 서명된 UKI. initramfs는 dracut-ng.
Secure Boot는 처음에 KEL 자체 키(사용자가 등록), 프로젝트가 자리 잡으면 shim 리뷰 신청.
레거시 BIOS는 지원하지 않는다.**

| 선택지 | 장점 | 단점 |
|---|---|---|
| **systemd-boot + UKI** (추천) | 가장 짧은 부팅 체인. 커널+initrd+cmdline을 PE 파일 하나로 묶어 통째로 서명. ukify/mkosi와 바로 연결. shim-review 리뷰어가 다룰 줄 아는 두 가지 중 하나. systemd와 같은 소스라 따로 유지할 프로젝트가 늘지 않음 | UEFI 전용 |
| GRUB 2.14 | BIOS+UEFI, 2.14부터 BLS·UKI 지원, shim 표준 경로 | 크고 CVE 이력이 많다(shim-review가 GRUB CVE 수정 목록을 따로 확인). GPLv3라 Microsoft가 직접 서명하지 않음 |
| Limine (v12.9.4) | BIOS+UEFI, 작다 | shim 리뷰어에게 낯섦("설득이 필요"), 엔터프라이즈 실적 적음 |
| EFI stub 직접 부팅 | 부트로더 없음 | 부팅 항목·롤백을 펌웨어(efibootmgr)에 의존, 펌웨어마다 동작이 다름 |

- aarch64 서버도 Arm SystemReady/SBBR에 따라 UEFI+ACPI로 부팅하므로 같은 체인을 쓴다.
- BIOS를 빼는 근거: SLES 16이 BIOS를 deprecated로 지정. (RHEL 10은 아직 지원하므로
  필요해지면 GRUB을 BIOS 전용 선택지로 추가할 수 있다.)
- initramfs: dracut-ng(최신 112, 분기 릴리스, 원래 dracut은 2022년 이후 릴리스 없음,
  Fedora·openSUSE가 사용). 나중에 mkosi-initrd를 재검토.

**Secure Boot 단계:**
1. Phase 3: KEL 테스트 키로 UKI와 systemd-boot에 서명하고, OVMF에 키를 등록해 Secure Boot
   부팅을 자동 테스트. 사용자 문서에는 `sbctl`로 자체 키 등록하는 방법(Microsoft 인증서
   유지 옵션 포함).
2. 나중: 법인, EV 인증서, 보안 연락처 2명, FIPS 140-2 Level 2 키 하드웨어가 준비되면
   shim-review 신청(조사상 준비 후에도 3~6개월). 새 shim은 Microsoft UEFI CA 2023으로만
   서명되므로 db에 2023 CA가 없는 장비는 지원 대상에서 빠진다는 점을 문서화.

### 4.9 설치 프로그램 — D-009

**추천: Phase 3에서 먼저 systemd-sysinstall(systemd 261+)을 평가한다. 맞으면 그대로 쓰고,
맞지 않으면 같은 부품(systemd-repart, bootctl, systemd-firstboot)으로 작은 `kel install`을
만든다. 무인 설치는 TOML 응답 파일. 클라우드/VM 이미지는 cloud-init(NoCloud).**

| 선택지 | 장점 | 단점 |
|---|---|---|
| **systemd-sysinstall / 자체 소형 설치기** (추천) | 디스크 선택 → repart로 파티션 → UKI·systemd-boot 설치까지 업스트림 부품으로. `--confirm=no` 무인 모드. 유지할 코드가 적다 | sysinstall은 아주 새로운 도구(systemd 261). 패키지 기반 설치(대상 루트에 패키지 설치)와 맞는지 확인 필요 |
| Anaconda + kickstart | 엔터프라이즈에 익숙한 kickstart | DNF/RPM과 Fedora 생태계에 묶여 있고 무겁다 |
| Calamares | 범용, 그래픽 | 데스크톱 지향, 무인 모드 문서 없음 |
| 처음부터 TUI 설치기 직접 개발 | 완전한 통제 | 1인 유지 비용 |

설치 흐름(초안): 디스크 선택 → systemd-repart(ESP + 루트, 선택 시 LUKS2) → 대상 루트에
ISO 안의 로컬 저장소로 베이스 패키지 설치 → `bootctl install` + UKI → systemd-firstboot
(호스트 이름, 시간대, root 비밀번호/SSH 키) → 재부팅. Discoverable Partitions 규격을 따라
fstab 없이 부팅하는 방식을 우선 검토한다.

### 4.10 업데이트 방식 — D-010

**추천: 패키지 단위 업데이트를 기본으로 한다. 이미지 기반은 같은 패키지로 만드는
"변형판"으로 나중에(Phase 4 이후) 검토한다.**

| 선택지 | 장점 | 단점 |
|---|---|---|
| **패키지 단위** (추천) | 엔터프라이즈 관리자가 기대하는 방식. CVE를 패키지 하나씩 고쳐 배포. 패키지는 어차피 빌드·서명·SBOM의 단위라 추가 인프라가 가장 적다 | 원자적 롤백이 없다(나중에 Btrfs 스냅샷 연동 등으로 보완 가능) |
| bootc (OCI 이미지) | RHEL image mode와 같은 방향, 이미지를 ghcr로 무료 배포 가능, CNCF Sandbox | ostree/composefs 요구사항, 도구가 Fedora 중심. RHEL에서는 패키지 모드 시스템과 서로 변환할 수 없음 |
| systemd-sysupdate + A/B + UKI + dm-verity | 가장 강한 검증 부팅 | man 페이지상 아직 "experimental"(v262에서 다시 실험적 표시) |
| Btrfs 스냅샷(transactional-update) | 패키지 방식 유지 + 롤백 | Btrfs에 의존, 재부팅 필요 |

이미지 변형판을 만들게 되더라도 원천은 같은 서명된 패키지이므로, 지금 패키지 방식을
고르는 것이 나중 선택지를 막지 않는다.

### 4.11 KEL 자체 도구의 구현 언어 — D-011

**추천: Python 3, 표준 라이브러리만 사용(서드파티 의존성 0).** 단, KEL이 패키지
매니저를 직접 만들기로 한다면(D-002에서 직접 개발 선택 시) 그 부분은 Rust 또는 Go가 낫다.

KEL 자체 도구가 하는 일은 대부분 "조율"이다: 레시피 읽기, 의존성 그래프, 소스 내려받기와
검증, bubblewrap 호출, 패키지 매니저의 패키징/색인 명령 호출, SBOM 생성, 설치 프로그램.
무거운 일(압축, 서명, 의존성 풀기)은 C로 된 기존 도구가 한다.

| 선택지 | 장점 | 단점 |
|---|---|---|
| **Python 3 (stdlib만)** (추천) | **부트스트랩 비용 0**: systemd(meson, jinja2)·glibc 빌드에 어차피 Python이 필요해서 새 의존성이 생기지 않는다. `tomllib`(3.11+), `hashlib`, `tarfile`, `subprocess`, `json`이 표준 라이브러리에 있다. 고치기 빠르고 AI와 협업하기 쉽다. Chimera의 cbuild가 같은 방식으로 독립 배포판 전체를 빌드한다(4.3 참조) | 동적 타입이라 큰 코드에서 실수 위험(타입 힌트 + 테스트로 보완). 표준 라이브러리에 ed25519 같은 서명 기능이 없다(서명은 패키지 매니저/외부 도구에 맡김) |
| Go | 정적 단일 바이너리, 표준 라이브러리 풍부(ed25519, tar), 재현 가능 빌드 쉬움 | Go 자체를 부트스트랩해야 함(이전 Go 필요). 셀프 호스팅에 Go 패키지가 먼저 있어야 함 |
| Rust | 가장 안전, 패키지 매니저 같은 핵심 도구에 적합 | rustc+LLVM 빌드가 무겁다(이 호스트 디스크·시간에 부담). 셀프 호스팅 전에 LLVM과 Rust를 먼저 패키징해야 함 |
| 셸 | 의존성 없음 | 의존성 그래프·서명·오류 처리 같은 복잡한 로직에 부적합 |

규칙(제안): 도구는 Python 3.11 이상 표준 라이브러리만 쓴다. 외부 프로그램(bwrap, 패키지
매니저, 서명 도구)은 `subprocess`로 부르고 버전을 확인한다. 타입 힌트를 쓰고 단위 테스트를 둔다.

### 4.12 커널 정책 — D-012

**추천: kernel.org LTS를 추적한다. 메이저 릴리스마다 출시 시점의 최신 LTS를 쓰고,
업스트림 EOL이 다가오면 같은 메이저 안에서 다음 LTS로 옮긴다(리베이스). kABI는
보장하지 않는다.** 개발 기간(Phase 1~3)에는 현재 LTS인 6.18을 쓰고, 7.4가 LTS로
지정되면(추정: 2026-12) 옮길지 검토한다.

| 선택지 | 장점 | 단점 |
|---|---|---|
| **최신 LTS 추적 + 메이저 안에서 리베이스** (추천) | 업스트림 stable 팀이 백포트를 해 준다(1인 프로젝트에 필수). 최신 하드웨어 지원 | 메이저 수명 중 커널 메이저 버전이 바뀜 → 회귀 테스트 필요, 외부 커널 모듈 재빌드 |
| 하나의 LTS 고정 + 직접 백포트 | RHEL식 안정성 | EOL 이후 백포트는 1인으로 불가능 (커널 CNA가 CVE를 대량 발행) |
| CIP SLTS 커널(6.12 → 2035년 중반) | 10년 수명 | CIP 회원사 설정 중심으로 유지, 범용 서버 드라이버 전체를 보장하지 않음 |
| 메인라인 stable 추적 | 최신 기능 | 9~10주마다 메이저 변경, 엔터프라이즈 안정성과 맞지 않음 |

LTS EOL(현재 표): 6.18·6.12 → 2028-12, 6.6·6.1 → 2027-12. 새 LTS는 처음에 2년으로
시작하고 연장될 수 있다.

### 4.13 릴리스 주기, 지원 기간, 버전 체계 — D-013

**추천: 메이저는 3년마다, 메이저마다 5년 지원(앞 3년 일반 지원 + 뒤 2년 보안 전용).
일반 지원 기간에는 6개월마다 포인트 릴리스. 버전은 `major.minor`(예: KEL 1.0, 1.1).
1.0 전에는 0.x 프리뷰.**

1인 유지보수의 상한은 "동시에 유지하는 안정 브랜치 2개 + 개발 브랜치 1개"로 본다.
3년 주기 × 5년 지원이면 겹치는 기간(2년)에도 안정 브랜치는 2개다.

```
year     0    1    2    3    4    5    6    7    8
KEL 1    [=====full=====][security]
KEL 2                   [=====full=====][security]
KEL 3                                  [=====full=====...
main     [======== development (next major, rolling) ========>
```

(full = 일반 지원 3년, security = 보안 전용 2년, main = 다음 메이저를 준비하는 개발 브랜치)

5년을 기준으로 잡는 이유: Ubuntu LTS 표준 지원, RHEL 일반(Full) 지원이 5년이고,
EU CRA가 제조사에 요구하는 최소 지원 기간도 5년이다(조사 기록 3.3, 3.5).

| 선택지 | 장점 | 단점 |
|---|---|---|
| **3년 주기 + 5년 지원** (추천) | "긴 지원"의 최소선(5년)을 지키면서 동시 브랜치 2개 유지 | 메이저 사이 3년 동안 새 기능은 포인트 릴리스로만. 1인에게는 여전히 무겁다 |
| 2년 주기 + 4년 지원 | 더 최신, 부담 비슷 | 4년은 엔터프라이즈 기준으로 짧다 |
| Alpine식(6~12개월 주기 + 2년 지원) | 1인에게 가장 현실적 | "긴 지원"이라는 목표와 맞지 않음 |
| 10년(RHEL식) | 엔터프라이즈 기대치에 가장 가까움 | 1인으로 불가능에 가깝다(동시 브랜치 3~4개, 업스트림 EOL 이후 직접 백포트). 참고로 Debian LTS는 2026년 8월 기준 유급 기여자 19명이 운영 |
| 롤링만 | 유지 부담 최소 | 지원 기간 개념이 약해 엔터프라이즈 목표와 충돌 |

업스트림 수명과 맞추기(1.0을 2027년 하반기로 가정한 예시):
- OpenSSL 4.2 LTS(2027-04 ~ 2032-04 예정)가 KEL 1의 5년과 거의 겹친다.
- GCC 브랜치는 약 3.5년이라 KEL 1 후반에는 컴파일러를 고정한 채 유지한다(보안 영향이 작음).
- 커널 LTS는 처음 2년만 약속되므로 메이저 수명 중 1~2회 LTS 리베이스가 필요하다(4.12).

버전과 브랜치:
- os-release `VERSION_ID="1.0"`, `SUPPORT_END`는 각 메이저의 지원 종료일.
- git 브랜치 `main`(개발) / `kel-1`(안정, 메이저별) / 태그 `v1.0`, `v1.1`.
- 패키지 버전: `<업스트림 버전>-r<KEL 리비전>` (예: `zlib-1.3.2-r0`, apk 관례).

지원의 정의(초안): "보안 업데이트는 최선 노력(best-effort), SLA 없음"을 명시한다.
목표치(예: 치명적 CVE는 업스트림 수정 공개 후 7일 내 배포)는 Phase 4 파이프라인을
만든 뒤 실제 처리 시간을 재고 정한다.

### 4.14 서명과 신뢰 체인 — D-014

**추천: 두 단계 키. 오프라인 "루트 키"(사용자가 보관, 저장소에 절대 없음)가 온라인
"저장소 서명 키"를 인증하고, 저장소 서명 키가 패키지와 색인에 서명한다. 개발용으로는
세션마다 버리는 임시 키를 쓴다.**

```
 업스트림 서명 키 (keys/upstream/, 공개)  ── 소스 tarball 검증
 KEL 루트 키 (오프라인, 사용자 보관)       ── 저장소 키 인증, 키 교체/폐기 공지에 서명
   └─ 저장소 서명 키 (온라인, 1년 주기 교체) ── 패키지·저장소 색인 서명
 개발용 임시 키 (세션마다 생성, 배포 금지)  ── Phase 1~3 테스트 저장소
```

- 들어오는 쪽: 모든 소스는 sha256(또는 더 강한 해시)로 고정. 업스트림이 서명을 제공하면
  (GNU, kernel.org 등) 서명도 검증하고 공개 키는 `keys/upstream/`에 고정.
- 나가는 쪽: 패키지 매니저가 서명을 검증하지 못하면 설치를 거부하는 것이 기본값.
- 개인 키 보관 위치는 사용자가 정한다(로컬 장비, 하드웨어 토큰 등). CI에서 서명한다면
  저장소 서명 키만 CI 비밀 저장소에 두고, 루트 키는 절대 온라인에 두지 않는다.
- 키 교체·폐기 절차와 리허설은 Phase 2 완료 조건에 넣는다.

### 4.15 빌드 인프라와 산출물 보관 ("빌드 팜 없이") — D-015

현재 작업 세션은 임시 컨테이너(4 vCPU, 디스크 31GB, KVM 없음)라 결과물이 남지 않는다.
**추천: 개발과 검증은 이 세션에서, 정기적이거나 무거운 빌드와 aarch64 네이티브 빌드는
GitHub Actions(공개 저장소라 무료)로. 서명은 CI 밖에서.**

| 선택지 | 장점 | 단점 |
|---|---|---|
| 이 세션만 사용 | 추가 설정 없음 | 매 세션 처음부터 다시 빌드(최종 GCC 하나만 테스트 포함 약 2.8시간 추정). aarch64 네이티브 불가 |
| **GitHub Actions (public 저장소)** (추천) | x64·arm64 러너 모두 4 vCPU/16 GB **무료** → aarch64를 에뮬레이션 없이 네이티브로 빌드. x64 러너에서 KVM으로 QEMU 테스트 가속. 캐시 10 GB, 아티팩트 90일 | 작업당 6시간, 디스크 14 GB → GCC·커널 같은 큰 빌드는 단계로 나눠야 함. **public 저장소의 아티팩트는 읽기 권한만 있으면 받을 수 있어 사실상 공개 배포**(사전 확인 필요) |
| 사용자 개인 장비 | 영구 저장, 키 보관에 적합 | 사용자가 직접 운영 |
| 오브젝트 스토리지(R2/B2/S3) | 저장소 호스팅에 적합 | 비용, 자격 증명 관리 |

- 공개 배포 경로(나중): GitHub Releases(파일당 2 GiB 미만, 총량 제한 없음) 또는 ghcr(OCI).
  공개 배포는 되돌리기 어렵기 때문에 시점과 방식을 따로 확인받는다.
- 바이너리를 어디든 올릴 때는 같은 곳에 대응 소스 묶음을 함께 올린다(4.16).
- 서명: Phase 1~3은 매번 버리는 개발용 키만 쓴다. 실제 저장소 서명 위치(로컬 vs CI 비밀
  저장소)는 Phase 4에서 정한다.

### 4.16 라이선스와 소스 공개 구조 — D-016

**추천:**
1. 모든 레시피에 SPDX 라이선스 식별자 필수. 없으면 빌드 실패.
2. 라이선스 원문은 패키지 안 `/usr/share/licenses/<패키지>/`에 설치.
3. 바이너리 저장소를 공개할 때는 **같은 위치에 정확히 그 빌드에 쓴 소스(업스트림 tarball +
   패치 + 레시피)를 함께 올린다**(GPL의 "대응 소스"를 서면 제안 없이 바로 제공하는 방식).
   릴리스 태그마다 소스 묶음을 보존한다.
4. 펌웨어처럼 재배포는 가능하지만 소스가 없는 것은 별도 구성요소(`nonfree-firmware` 등)로
   분리하고 기본 설치에서 선택 사항으로 둔다.
5. KEL이 직접 쓴 코드·레시피·문서의 라이선스: **MIT 추천**(단순하고 호환성이 넓음).
   대안: Apache-2.0(특허 조항), 0BSD(Arch 패키징 레시피 방식). 업스트림 패치는 해당
   업스트림의 라이선스를 따른다.
6. 라이선스 호환성 검사(예: GPL-2.0-only와 Apache-2.0 링크 조합)를 Phase 4 SBOM 단계에서
   자동화한다.

### 4.17 보안 기반 (Phase 4 미리보기) — D-017

Phase 4에서 구현하지만, 패키지 형식과 빌드 시스템에 영향을 주므로 방향은 지금 정한다.

**MAC 추천: SELinux, refpolicy 기반, "targeted" 방식**(네트워크 데몬부터 가두고 나머지는
unconfined). 1.0은 permissive로 시작하고 정책이 안정되면 enforcing으로 올리는 것도 선택지.

| 선택지 | 장점 | 단점 |
|---|---|---|
| **SELinux (refpolicy 기반)** (추천) | RHEL, SLE 16(AppArmor 제거), openSUSE가 쓰는 엔터프라이즈 표준. refpolicy가 연 3회 정도 릴리스 | 정책 유지가 무겁다. 파일 라벨을 패키지 설치 과정에 넣어야 한다(D-002와 연결). Fedora 수준의 정책 범위는 1인으로 불가능 |
| AppArmor | 경로 기반이라 프로파일이 쉽다. 라벨 불필요 | 엔터프라이즈 흐름이 SELinux 쪽(SUSE가 제거) |
| Landlock + systemd 샌드박스만 | 정책 유지 부담 최소 | 시스템 전체 MAC이 아님. "SELinux 등" 요구를 못 채움 |

**SBOM과 보안 공지(제안):**
- 빌드할 때 패키지마다 SPDX 3.0.1 JSON SBOM을 만든다(레시피 메타데이터 + 파일 해시 +
  소스 해시 + 라이선스). CISA 2026 최소 요소(작성자 서명, 도구 이름/버전, 구성요소 해시,
  라이선스)를 채운다. CycloneDX 1.7은 변환으로 제공.
- 보안 공지는 OSV 형식 + (apk 채택 시) Alpine 형식 secdb. 기존 취약점 스캐너가 읽을 수 있는
  가장 싼 방법이다. CSAF/VEX는 수요가 생기면.
- 커널 CVE는 연 수천 건이라 1인이 개별 분석할 수 없다 → LTS stable 업데이트를 전부 받는 정책
  (커널 CNA 권고와 같음).
- NVD 점수에 의존하지 않는다(2026-04-15부터 NIST는 KEV·연방·핵심 소프트웨어 CVE만 우선
  보강하고 나머지는 "예정 없음"으로 둠).

**SBOM 형식 (`kel sbom`, 구현됨):** 빌드된 바이너리 패키지마다 SPDX 3.0.1 JSON-LD 문서 하나를
`work/<arch>/repo/sbom/<패키지>-<버전>-r<리비전>.spdx.json`에 쓴다. 입력은 레시피(이름, 버전, 라이선스,
홈페이지, 소스 URL·sha256·서명, 패치), 패키징 때 남긴 매니페스트(파일 목록), `.apk` 파일 자체(sha256,
build-time, 파일별 sha256은 `apk adbdump`로 읽음)다. 셋의 버전·라이선스·파일 목록이 서로 맞지 않으면 만들지 않는다.
요소 이름과 관계 방향은 명세(<https://spdx.github.io/spdx-spec/v3.0.1/>)와 JSON-LD 컨텍스트에서 확인했다.

| 대상 | SPDX 3.0.1 표현 | 메모 |
|---|---|---|
| 문서 | `SpdxDocument` → rootElement `software_Sbom`(sbomType `build`) → rootElement 바이너리 패키지 | `Sbom`은 "패키지 하나를 기술하는 요소 묶음" |
| 바이너리 패키지 | `software_Package`: 이름, `<버전>-r<리비전>`, purl `pkg:apk/kel/<이름>@<버전>?arch=<arch>`, 홈페이지, suppliedBy KEL, builtTime, `.apk`의 sha256 | 스캐너가 읽는 패키지 요소에 구성요소 해시 |
| 배포 파일 | `hasDistributionArtifact` → `software_File` `<이름>-<버전>.apk`(sha256) | 서명되고 공개되는 실제 파일 |
| 패키지 내용 | `contains` → 파일·심볼릭 링크마다 `software_File`(sha256, 링크는 대상을 comment로) | 디렉터리는 넣지 않음 |
| 라이선스 | `hasDeclaredLicense` → `simplelicensing_LicenseExpression`(레시피의 SPDX 식) | concluded 라이선스는 주장하지 않음 |
| 업스트림 소스 | `software_Package`(downloadLocation, sha256, 서명 URL과 고정 키 지문은 externalRef `securityOther`) `generates` → 바이너리 패키지 | 3.0.1에는 generatedFrom이 없다 |
| 패치 | 첫 소스 `patchedBy` → `recipes/<이름>/patches/*.patch`(sha256) | 대응 소스(D-016)의 일부 |
| 작성 정보 | `CreationInfo`: createdBy KEL(Organization), createdUsing `kel <버전>`(Tool), created = 패키지 build-time | dataLicense CC0-1.0 |

같은 패키지는 항상 같은 바이트의 SBOM이 된다: 시각은 패키지를 빌드한 `SOURCE_DATE_EPOCH`(패키지
build-time) 하나뿐이고, 요소 ID는 `https://github.com/jgchoimd-web/KEL/spdx/<arch>/<이름>-<버전>#Package`처럼
이름·버전·아키텍처·경로에서 만들며, 명세 6장의 정규 직렬화(키 정렬, 공백 없음)로 쓴다. 단위 테스트가 구조(필수
필드, 참조가 문서 안에서 풀리는지)를 검사하고, `KEL_SPDX_SCHEMA`에 공식 JSON 스키마
(<https://spdx.org/schema/3.0.1/spdx-json-schema.json>) 사본을 주면 표준 라이브러리만으로 스키마 검증도 한다.
아직 없는 것: SBOM 서명, 의존성(`depends`, `so:`)을 다른 패키지의 SBOM과 잇는 관계, 빌드 단계에서 자동 생성.

**재현성과 공급망(제안):**
- `SOURCE_DATE_EPOCH`는 레시피의 마지막 변경 커밋 시각 등 결정적인 값으로 고정.
- 두 번 빌드해서 비교(Phase 1 stage 4/5부터), 차이는 diffoscope로 분석.
  목표치는 처음 90%, 장기적으로 Debian 수준(98%)에 근접.
- 빌드 provenance(in-toto/SLSA Build L1~L2)는 Phase 4.
- 호스트 GCC를 "믿는" 대신 "검증"하려면 live-bootstrap(x86 전용, 수 시간~하루, 결과는
  musl 기반 GCC 15.2)으로 만든 컴파일러로 KEL 툴체인을 한 번 더 빌드해 비교한다(DDC).
  Phase 4 선택 과제.

**EU CRA:** 수익화하지 않는 개인 프로젝트인 동안 의무는 없다. 상업화하면 운영체제는
Class I 제품이 되고 최소 5년 지원과 SBOM 등이 의무가 된다. 그래서 처음부터 기술 문서와
SBOM을 공개하고, 지원 기간도 5년을 기준으로 잡는다(4.13).

## 5. 부트스트랩 계획 (Phase 1 상세)

목표는 "호스트의 바이너리는 출발점으로만 쓰고, 최종 패키지는 전부 KEL이 만든
툴체인으로 빌드된다"를 **명령 하나로 반복 가능하게** 만드는 것이다. 구조는 LFS의
단계 구분(크로스 툴체인 → 임시 도구 → 격리 환경 안에서 최종 빌드)을 따르되,
손으로 따라 하는 대신 레시피와 `kel bootstrap` 명령으로 자동화한다.

```
 Ubuntu 24.04 호스트 (출발점일 뿐, 결과물에 들어가지 않음)
   │  stage 0: 호스트 점검 (필요 도구와 최소 버전 확인)
   ▼
 stage 1: 크로스 툴체인        → $WORK/stage1/tools (x86_64-kel-linux-gnu-*)
   binutils → GCC pass 1 → Linux API headers → glibc → libstdc++
   ▼
 stage 2: 크로스 컴파일 임시 도구 → $WORK/stage2/rootfs
   bash, coreutils, make, sed, tar, xz, ... binutils pass 2, GCC pass 2
   ▼  (여기서부터 호스트 /usr 를 보지 않는 격리 환경: bubblewrap)
 stage 3: 격리 환경 안에서 kel 빌드 도구로 "진짜" 패키지 빌드 → KEL 패키지 저장소 v0
   glibc, GCC, binutils, ... 패키지 매니저, bubblewrap, Python
   ▼
 stage 4: stage 3 패키지만으로 만든 빌드 루트에서 전체 재빌드 → 저장소 v1  (셀프 호스팅)
   ▼
 stage 5: stage 4 패키지로 한 번 더 재빌드 → 저장소 v2, v1과 비트 단위 비교 (재현성 검증)
```

stage 0 호스트 점검 기준은 LFS 13.1의 호스트 요구사항(Bash 3.2, Binutils 2.13.1,
Bison 2.7, Coreutils 8.1, Diffutils 2.8.1, Findutils 4.2.31, Gawk 4.0.1, GCC 5.4, Grep 2.5.1a,
Gzip 1.3.12, M4 1.4.10, Make 4.0, Patch 2.5.4, Perl 5.8.8, Python 3.4, Sed 4.1.5, Tar 1.22,
Texinfo 5.0, Xz 5.0.0, 커널 5.10)에 KEL 도구용 Python 3.11+와 bubblewrap을 더한 것으로
시작한다. 현재 호스트에는 gawk와 texinfo가 없지만 apt로 설치할 수 있음을 확인했다.
(GCC 15 이상을 빌드하려면 C++14 호스트 컴파일러가 필요한데 호스트 GCC 13.3이면 충분하다.
glibc 2.44가 요구하는 GCC 12.1+/binutils 2.39+는 stage 1에서 만든 KEL 크로스 툴체인이 충족한다.)
출처: <https://www.linuxfromscratch.org/lfs/view/stable-systemd/chapter02/hostreqs.html>

### 5.1 단계별 검증 기준

| 단계 | 통과 조건 |
|---|---|
| stage 1 | 크로스 GCC로 만든 hello world가 KEL sysroot의 glibc 동적 링커(`/lib64/ld-linux-x86-64.so.2`)를 요구하고, `readelf -l`로 확인됨 |
| stage 2 | 임시 루트에서 `bwrap`으로 셸을 띄우고 호스트 `/usr` 없이 `gcc`로 C/C++ 프로그램을 빌드·실행 |
| stage 3 | 최소 베이스 패키지 전체가 빌드되고 패키지 매니저로 빈 디렉터리에 설치 가능 |
| stage 4 | stage 3 패키지만 들어간 빌드 루트에서 모든 패키지 재빌드 성공 (= 셀프 호스팅) |
| stage 5 | stage 4와 stage 5 결과물 비교: 다른 파일 목록과 원인을 기록하고 0을 목표로 줄여 간다 |
| 호스트 오염 검사 | 최종 패키지의 ELF `.comment`에 `Ubuntu` 등 호스트 컴파일러 흔적이 없음, RPATH/RUNPATH에 빌드 경로 없음, 호스트 경로 문자열 없음 |

stage 4/5 비교는 GCC가 자기 빌드에서 하는 stage 2/3 비교와 같은 원리의
고정점(fixed point) 검사다. 결과가 같으면 호스트 컴파일러의 우연한 흔적(버전 문자열,
최적화 차이 등)이 결과물에 남지 않았다는 근거가 된다. 다만 호스트 컴파일러가 일부러
자기 복제 백도어를 심는 공격(trusting trust)까지 배제하지는 못한다. 그 보증에는
서로 독립적인 컴파일러 두 개로 빌드한 결과를 비교하는 DDC(Diverse Double-Compiling)나
live-bootstrap 같은 전체 소스 부트스트랩이 필요하고, Phase 4에서 검토한다.

**비교 도구 (`kel compare A B`, 구현됨):** 두 저장소(`.apk`가 있는 디렉터리 또는 그 부모)의 패키지를 이름으로
짝짓고 한쪽에만 있는 패키지를 보고한다(같은 이름이 여러 버전이면 가장 새 버전). `.apk`가 비트 단위로 같으면 끝이다.
다르면 apk 자체로 읽는다(v3 형식을 직접 해석하지 않음, 4.2): `apk adbdump`로 메타데이터(패키지 필드 전부와
경로마다 종류·모드·소유자·링크 대상·sha256·mtime·xattr)를, `apk extract`로 파일을 풀어 메타데이터와 맞는지
해시를 다시 계산해 확인한 뒤 비교한다. 내용이 다른 ELF 파일은 다른 섹션 이름을 알려 준다(섹션 헤더를 파이썬으로
읽으므로 readelf가 필요 없다). 내용과 메타데이터가 같은데 `.apk`만 다르면 서명이나 압축만 다른 것이고, 이것도
차이로 센다(같은 RSA 키의 apk 서명은 결정적이다, D-019).

| 주제 | 규칙 | 이유 |
|---|---|---|
| 풀기 | 패키징처럼 user namespace의 uid 0으로 `apk --allow-untrusted extract --no-chown`, 그 namespace 안에서만 유효한 `CAP_DAC_OVERRIDE` 추가 | 비특권 사용자도 읽기 전용 디렉터리가 든 패키지를 풀 수 있다. 소유자는 메타데이터로 비교. 서명 키가 다른 저장소끼리도 비교 |
| 결과 | Markdown 보고서(표준 출력, `--report FILE`)와 JSON 요약(`--json FILE`, `-`면 표준 출력): 같은 패키지, 다른 패키지의 경로와 차이 종류(missing, type, mode, owner, target, content, mtime, xattrs), 메타데이터 차이 | 사람이 읽는 보고서와 stage 5 자동 판정 |
| 종료 코드 | 하나라도 다르거나 한쪽에만 있으면 1 | |
| 더 보기 | `--keep DIR`이면 푼 파일을 `DIR/a/<이름>`, `DIR/b/<이름>`에 남김(소유자 읽기·쓰기 권한이 더해짐) | diffoscope로 원인 분석(4.17) |

### 5.2 aarch64

같은 레시피를 `kel bootstrap --arch aarch64`(타깃 `aarch64-kel-linux-gnu`)로 돌려
stage 1~2를 크로스로 만든다. stage 3 이후는 (a) 크로스 컴파일로 계속 가거나
(b) 네이티브 aarch64 환경(GitHub Actions arm64 러너, D-015)에서 진행한다. 레시피 형식은
처음부터 크로스 빌드를 전제로 설계한다(빌드 머신/타깃 구분, `CHOST`/`CBUILD` 변수).
이 호스트에서 qemu-user 에뮬레이션으로 aarch64를 빌드하는 방식은 네이티브보다 느려서
기본 계획에서 뺀다(필요해지면 Phase 2에서 실측). 부팅 테스트는 TCG로 한다(측정값 16초).

### 5.3 디스크 31GB 안에서 돌리기

- 소스 tarball 캐시(내용 주소 저장, sha256 이름)와 빌드 작업 디렉터리를 분리한다.
- 패키지 하나를 빌드하면 작업 디렉터리를 바로 지운다. 실패할 때만 남긴다.
- 동시에 큰 패키지 두 개를 빌드하지 않는다(GCC 6.6GB, glibc 3.3GB).
- 세션이 끝나면 사라지므로 시간이 많이 드는 결과물(stage 1 툴체인, 패키지 저장소)은
  보관소에 올린다(4.15 참조). 보관소가 없으면 매 세션 처음부터 다시 만든다.

## 6. 저장소 구조 (제안)

```
KEL/
├── README.md
├── LICENSE                  # KEL 자체 코드/레시피 라이선스 (D-016)
├── docs/
│   ├── DESIGN.md  DECISIONS.md  PROGRESS.md
│   └── research/            # 조사 기록 (날짜별, 출처 포함)
├── tools/kel/               # KEL 빌드/저장소/이미지 도구 (D-011)
├── recipes/<이름>/
│   ├── recipe.toml          # 메타데이터 + 빌드 단계
│   └── patches/             # 업스트림 패치 (각 파일 머리에 이유와 업스트림 상태)
├── bootstrap/               # stage 0~5 정의 (어떤 레시피를 어떤 프로필로)
├── keys/
│   ├── upstream/            # 업스트림 소스 서명 검증용 공개 키 (GNU keyring 등)
│   └── kel/                 # KEL 저장소 서명 공개 키 (개인 키는 절대 여기 두지 않음)
├── images/                  # 설치 ISO, 클라우드 이미지 정의
├── tests/                   # 설치/업데이트/부팅 자동 테스트 (QEMU)
└── .github/workflows/       # CI (D-015 결정에 따라)
```

## 7. 단계별 로드맵과 완료 기준

| 단계 | 핵심 작업 | 완료 기준 (실제로 돌려서 확인) |
|---|---|---|
| **Phase 1** 부트스트랩 | `kel` 도구 뼈대, 크로스 툴체인, 임시 도구, stage 3~5 | 5.1의 stage 1~4 통과, stage 5 비교 보고서 |
| **Phase 2** 빌드 시스템/패키지 | 레시피 트리, 격리 빌드, 서명, 저장소 생성, 설치/업데이트/삭제 | 빈 루트에 설치 → 새 버전 저장소로 업데이트 → 삭제가 자동 테스트로 통과, 서명 안 된/변조된 패키지는 거부 |
| **Phase 3** 첫 부팅 이미지 | 커널 설정, 부트로더, initramfs, 설치 ISO, 설치 프로그램 | QEMU(UEFI)에서 ISO 부팅 → 디스크 설치 → 재부팅 → 네트워크 저장소에서 패키지 설치, 자동화된 테스트로 x86_64 통과 |
| **Phase 4** 엔터프라이즈 | 보안 업데이트 파이프라인, MAC, SBOM, 재현성 검증, LTS 브랜치 | CVE 하나를 가정해 패치 → 빌드 → 서명 → 배포 → 설치된 시스템 업데이트까지 리허설, SBOM 생성, 재빌드 비교 보고서 |
| **Phase 5** 문서 | 설치/패키징 가이드, 릴리스 노트, 지원 정책 | 문서만 보고 새 환경에서 설치와 패키지 추가가 재현됨 |

## 8. 위험 요소와 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| 1인 유지보수 한계 (보안 업데이트 지연) | 엔터프라이즈 신뢰 하락 | 패키지 수 제한, 업스트림 LTS가 있는 구성요소 우선, CVE 추적 자동화, 지원 약속은 현실적으로(최선 노력, SLA 없음 명시) |
| 세션이 임시적이라 산출물 유실 | 긴 빌드 반복 | 레시피 중심 설계 + 산출물 보관소(D-015) |
| 디스크 31GB | 대형 패키지(LLVM, Rust) 빌드 실패 | 단계적 빌드와 정리, 필요하면 CI 러너나 사용자 장비 활용 |
| 업스트림 소스 서버 장애/차단 | 빌드 중단 | 소스 캐시와 미러, 레시피에 체크섬 고정 |
| Secure Boot 서명(shim) 확보 어려움 | 기본 설정 PC/서버에서 부팅 불편 | 초기에는 자체 키 등록 방식, 프로젝트가 자리 잡은 뒤 shim 리뷰 신청 |
| 서명 키 유출 | 공급망 공격 | 오프라인 루트 키 + 온라인 서명 키 분리, 키 교체 절차를 Phase 2에 포함 |
| 라이선스 위반 | 배포 불가 | 레시피에 SPDX 라이선스 필수, 바이너리와 같은 위치에 소스 공개, 라이선스 검사 자동화 |
| aarch64 네이티브 환경 없음 | aarch64 지연 | 처음부터 크로스 빌드 가능한 레시피 형식 + GitHub Actions arm64 러너(공개 저장소 무료, D-015) |

## 9. 결정 상태

전체 목록과 상태는 [DECISIONS.md](DECISIONS.md)에 있다. 2026-10-22에 사용자가 결정을
위임해서 D-001~D-017과 D-019, D-020, D-024(정책), D-025를 확정했다. 남은 보류 항목
(D-018 sudo, D-021 커널 7.4 전환, D-022 서명 위치, D-023 기본 파일시스템)은 해당 단계에서
정하고 기록한다. 바이너리 첫 공개만은 실행 직전에 사용자에게 한 번 확인한다(D-024).

## 10. 참고 자료

- [작업 환경 측정 기록](research/2026-10-22-environment.md): CPU·메모리·디스크·네트워크,
  SBU 측정, QEMU TCG 부팅 시간, bubblewrap 검증, 업스트림 서명 검증
- [업스트림 조사 기록](research/2026-10-22-upstream-survey.md): 이 문서의 모든 버전·일정·정책
  사실과 출처 URL
- [apk-tools v3 사전 검증](research/2026-10-22-apk-v3-poc.md): 빌드, 서명·설치·업그레이드·삭제,
  변조 거부, 재현성 실험
