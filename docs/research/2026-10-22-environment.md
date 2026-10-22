# 작업 환경 측정 기록 (2026-10-22)

Phase 0에서 작업 환경을 직접 확인한 결과다. 숫자는 모두 이 세션에서 실제로
명령을 돌려 얻은 값이다. 클라우드 세션 컨테이너는 매번 새로 만들어지므로
다음 세션에서는 값이 달라질 수 있다. 큰 작업 전에는 다시 확인한다.

## 1. 호스트

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Ubuntu 24.04.5 LTS (noble) | `/etc/os-release` |
| 커널 | 6.18.44-fc-v140, x86_64 | `uname -a` |
| 형태 | KVM 가상 머신 안의 컨테이너, root 권한, 임시(ephemeral) | `lscpu`, `id` |
| CPU | Intel Xeon @ 2.10GHz, 4 vCPU (family 6 model 207), AVX-512/AMX 플래그 있음 | `lscpu` |
| 가상화 | `vmx` 플래그 없음, `/dev/kvm` 없음 → **QEMU는 TCG(소프트웨어 에뮬레이션)만 가능** | `/proc/cpuinfo`, `ls /dev/kvm` |
| 메모리 | 15 GiB, 스왑 없음 | `free -h` |
| 디스크 | 루트 파일시스템 252G 중 **쓸 수 있는 여유 약 31G** (세션 할당량) | `df -h` |
| 네임스페이스 | `unshare --user --map-root-user --mount --pid --net` 성공 → 비특권 격리 빌드 가능 | 직접 실행 |
| 블록 장치 | `/dev/loop*`, `/dev/loop-control`, `/dev/fuse` 있음 → 디스크 이미지 조립 가능 | `ls /dev` |
| cgroup | v1 혼합 + cgroup2(`/sys/fs/cgroup/unified`) | `mount` |
| capability | `cap_sys_resource` 외 전부 | `capsh --print` |

## 2. 네트워크

- 외부 HTTPS는 클라우드 환경의 정책 프록시를 거친다.
- `cdn.kernel.org` 다운로드 속도 약 **25 MB/s** (linux-6.12.tar.xz 148MB를 5.9초).
- 접속 확인: `cdn.kernel.org`, `git.kernel.org`, `ftp.gnu.org`, `sourceware.org`,
  `download.savannah.gnu.org`, `releases.llvm.org`, `static.rust-lang.org`,
  `go.dev`, `pypi.org`, `deb.debian.org`, `archive.ubuntu.com`, `ports.ubuntu.com`,
  GitHub 공개 저장소(`git ls-remote`)와 릴리스 첨부 파일.
- 느림(약 20초): `musl.libc.org`, `busybox.net`.
- 실패: `gitlab.alpinelinux.org` (연결 리셋). github.com 웹 페이지 일부는 프록시가 403.
  → 소스는 tarball 미러 우선, git은 대체 미러를 레시피에 함께 적는다.

## 3. 호스트 도구

이미 있음: gcc 13.3, binutils 2.42, make 4.3, cmake 3.28, ninja 1.11, bison 3.8.2,
m4 1.4.19, perl, python 3.13, rustc/cargo 1.97, go 1.24.7, clang/lld 18, gpg 2.4.4,
xz 5.4.5, git 2.43, curl 8.5.

없지만 `apt-get`으로 설치 가능함을 확인(후보 버전): gawk 5.2.1, flex 2.6.4,
texinfo 7.1, meson, bubblewrap 0.9.0, qemu-system-x86/arm 8.2.2, ovmf,
qemu-efi-aarch64, xorriso 1.5.6, mtools 4.0.43, squashfs-tools 4.6.1,
erofs-utils 1.7.1, mkosi 20.2, diffoscope 259, reprotest 0.7.26, minisign 0.11,
signify-openbsd 31, sq 0.33.0, sbsigntool 0.9.4, systemd-ukify 255.4.

## 4. 빌드 처리량 (SBU)

LFS 12.4는 SBU를 "binutils pass 1을 **코어 1개**로 configure+make+install 하는
시간"으로 정의하고, 나머지 패키지 시간은 `-j4` 기준으로 적는다
(<https://www.linuxfromscratch.org/lfs/view/stable/chapter04/aboutsbus.html>).

binutils 2.47 크로스 빌드(`--target=x86_64-kel-linux-gnu`, LFS pass 1 옵션)로 측정:

| 조건 | 시간 |
|---|---|
| `make -j1` (LFS 정의의 1 SBU) | **216.9초** |
| `make -j4` | 82.5초 |

이 값과 LFS 12.4 표기값으로 어림한 시간 (실측은 Phase 1에서):

| 패키지 (LFS 12.4) | LFS 표기 | 이 호스트 추정 | 빌드 공간 |
|---|---|---|---|
| GCC 15.2 pass 1 | 3.8 SBU | 약 14분 | 5.4 GB |
| glibc 2.42 (8장) | 12 SBU | 약 43분 | 3.3 GB |
| GCC 15.2 (8장, 테스트 포함) | 46 SBU | 약 2시간 46분 | 6.6 GB |
| Linux 6.16.1 커널 | 0.4–32 SBU (보통 2.5) | 약 1.5분–1.9시간 (보통 9분) | 1.7–14 GB |

참고: 업스트림 tarball 서명을 GNU keyring(`https://ftp.gnu.org/gnu/gnu-keyring.gpg`)으로 검증했다.

| tarball | 결과 | 서명 키 (주 키 지문) | sha256 |
|---|---|---|---|
| binutils-2.47.tar.xz | Good signature | Nick Clifton `3A24 BC1E 8FB4 09FA 9F14 3718 13FC EF89 DD9E 3C4F` | (측정 시 미기록) |
| gcc-16.2.0.tar.xz (103M) | Good signature | Richard Guenther `1397 5A70 E63C 361C 73AE 69EF 6EEB 81F8 981C 74C7` | `e6738e29597f733270731aa90600f37ffdc045079dfc27ec7e8192cc81085c3e` |
| glibc-2.44.tar.xz (20M) | Good signature, **단 키가 `[expired]`로 표시** | Andreas K. Huettel `35B1 7DF5 7525 77CA 0C54 1CEB 94BF DF44 84AD 142F` | `37f600f2bef3c5e8300147059568b2a2e40a7ad6ccc65ce942556d49429cc667` |

glibc 사례처럼 keyring에 들어 있는 키 사본이 오래되어 만료로 보일 수 있다. KEL은
서명 검증을 "keyring에 있으면 통과"로 하지 않고, 레시피에 **키 지문을 고정**하고
키 갱신 절차를 따로 둔다. (sha256 고정이 1차 방어선이고 서명은 처음 레시피를 만들거나
버전을 올릴 때의 진위 확인 수단이다.)
`x86_64-kel-linux-gnu` 처럼 vendor 자리에 `kel`을 쓴 타깃 triplet이 binutils
`config.sub`에서 문제없이 받아들여지는 것도 확인했다.

## 5. QEMU TCG 부팅 속도

호스트 배포판의 커널(Ubuntu 6.8 generic)과 정적 busybox initramfs로, 커널 시작부터
init이 실행되고 전원이 꺼질 때까지의 벽시계 시간을 쟀다. (KEL 결과물이 아니라
측정용이다.)

| 구성 | 벽시계 시간 | init 도달 시점(uptime) |
|---|---|---|
| x86_64, `-kernel` 직접 부팅 | 5.8초 | 3.13초 |
| x86_64, OVMF(UEFI) + q35 | 8.6초 | 3.75초 |
| aarch64 `virt`, `-kernel` 직접 부팅 | 13.2초 | 9.73초 |
| aarch64 `virt`, AAVMF(UEFI) | 16.3초 | 11.30초 |

- TCG의 기본 CPU 모델 `qemu64`는 x86-64-v1 기능만 보인다 (SSE4.2/POPCNT 없음).
- TCG `-cpu max`는 AVX/AVX2/BMI2/FMA/MOVBE를 보여 **x86-64-v3까지 테스트 가능**,
  AVX-512(v4)는 없음. → KEL 테스트 스크립트는 CPU 모델을 반드시 명시해야 한다.

## 6. 격리 빌드 사전 검증 (bubblewrap)

Ubuntu의 bubblewrap 0.9.0을 설치해 확인했다.

- root로 `bwrap --unshare-all --proc /proc --dev /dev --tmpfs /tmp ...` 실행 성공.
  안에서 PID 1은 bwrap이고, 이름 해석(`getent hosts example.com`)이 실패해
  네트워크가 차단됨을 확인.
- **일반 사용자**(`kelbuild`)로 `bwrap --unshare-all --uid 0 --gid 0 ...` 실행 성공
  (안에서 uid 0으로 보이고 tmpfs에 파일 생성 가능, 네트워크 차단).
- 일반 사용자로 `unshare --user --map-root-user --mount` 후 tmpfs 마운트 성공.

→ root 없이 네트워크가 끊긴 격리 환경에서 패키지를 빌드할 수 있다.

## 7. 시사점

1. **빌드 팜이 없고 세션이 임시적이다.** 빌드 결과물(툴체인, 패키지, 소스 캐시)은
   세션이 끝나면 사라진다. 레시피만으로 처음부터 다시 만들 수 있어야 하고
   (원래 목표와 일치), 시간이 드는 산출물은 따로 보관할 곳이 필요하다.
2. **디스크 31GB.** GCC 하나가 빌드 중 6.6GB를 쓴다. 큰 패키지는 한 번에 하나씩
   빌드하고 작업 디렉터리를 즉시 지우는 방식이어야 한다. LLVM/Rust 같은 대형
   패키지는 별도 계획이 필요하다.
3. **KVM 없음.** 부팅/설치 테스트는 TCG로 충분히 빠르다(수십 초). 대신 aarch64를
   에뮬레이션으로 "빌드"하는 것은 비현실적이므로 aarch64는 크로스 빌드 또는
   네이티브 러너가 필요하다.
4. **user namespace 사용 가능.** root 없이도 bubblewrap/unshare 기반 격리 빌드를
   할 수 있다.
