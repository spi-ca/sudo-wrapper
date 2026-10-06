# sudo-wrapper

[![CI](https://github.com/spi-ca/sudo-wrapper/actions/workflows/ci.yml/badge.svg)](https://github.com/spi-ca/sudo-wrapper/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Linux x86_64용 최소 Zig 실행 래퍼. sudo 기능·인증·권한 상승을 다시 구현하지 않는다.

| 산출물 (`zig-out/bin/`) | 크기 | 고정 실행 대상 |
|---|---:|---|
| `sudo` | **166 bytes** | `/usr/bin/sudo-rs` |
| `sudoedit` | `sudo`를 가리키는 상대 symlink | `/usr/bin/sudo-rs`의 편집 모드 |
| `visudo` | **168 bytes** | `/usr/bin/visudo-rs` |

두 ELF의 논리적 파일 크기 합계는 **334 bytes**다. symlink와 파일시스템 메타데이터,
블록 할당량은 별도다. 두 실행 파일은 같은 `src/main.zig`에서 빌드하며, visudo용
빌드에서는 대상 문자열만 치환한다. 런타임 이름 분기는 없다.

## 실행 경로

- 성공: 고정 절대 경로에 대한 `execve(path, argv, envp)` syscall **하나**.
- 실패: 출력 없이 `exit(127)` syscall. 모든 execve 오류를 같은 코드로 처리한다.
  상속된 seccomp 정책이나 신호가 종료를 제한하면 관찰되는 상태는 달라질 수 있다.
  exit syscall이 반환하는 경우 `ud2`로 trap하며, sandbox를 우회하지 않는다.
- `argv[0]`을 포함한 인자, 환경, PID를 그대로 전달한다.
- 셸, PATH 검색, fork, 할당, libc, Zig 기본 시작 코드, 동적 로더가 없다.
- 옵션·환경을 재해석하거나 실패 시 다른 프로그램으로 fallback하지 않는다.
- 비밀번호를 읽거나 보관하지 않는다. mlock은 추가하지 않는다.

초기 스택에서 argc만 소비하고 그 자리를 작은 push/pop 명령열의 임시 공간으로
재사용한다. argv/envp 배열과 문자열은 수정하지 않는다. CALL은 인라인 대상
문자열을 건너뛰고 그 주소를 스택에 넣으며, 바로 POP으로 회수한다. 함수/라이브러리
호출이나 추가 syscall이 아니라 위치 독립 주소 획득용 CPU 명령열이다.

## 빌드 및 검증

요구 도구: Zig **0.17.0**(검증 버전), GNU binutils **2.41 이상**의 objcopy
(`--strip-section-headers` 필요), 일반적인 POSIX shell/coreutils.
Zig가 PATH에 없으면 mise를 사용한다. `ZIG=/절대/경로/zig`,
`OBJCOPY=/절대/경로/objcopy`로 빌드 도구를 지정할 수 있다.

```sh
./build.sh
stat -c '%n %s bytes' zig-out/bin/sudo zig-out/bin/visudo
ls -l zig-out/bin/sudoedit
readelf -h -l -r zig-out/bin/sudo zig-out/bin/visudo
python3 tests/test_wrapper.py
python3 tests/test_package.py
./package.sh
```

인자 없는 빌드는 두 ELF와 sudoedit 링크를 생성한다. sudoedit 위치에 다른 파일이나
다른 symlink가 있으면 교체하지 않고 실패한다. 기존의 `./build.sh source.zig output`
형식은 비권한 테스트 픽스처용으로 유지한다.

검증에는 Python 3, strace와 Zig의 C 컴파일러가 필요하다. 테스트는 임시 디렉터리의
C probe만 실행한다. **실제 sudo-rs/visudo-rs의 인증·정책·권한 상승을 테스트하지 않는다.**
인자·환경·PID·종료 코드 전달, 링크 호출, 위조/빈/긴/비UTF-8 argv[0], Linux가
정규화한 빈 인자 벡터, 별도 visudo 대상, 실패 경로, syscall 및 ELF 구성을 검증한다.
추가 syscall로 exec 직전에 멈춘 비권한 픽스처의 `/proc/PID/maps`를 읽어,
GNU_STACK 없이도 스택이 `rw-p`, 실행 파일 매핑이 `r-xp`인지 확인한다.
이 계측 코드는 산출물에 포함되지 않는다.

Linux가 사용하는 ELF/프로그램 헤더는 유지하고, 불필요한 섹션 헤더만 GNU objcopy로
제거한다. sudo의 구성은 **헤더 120 + 명령열 29 + 대상 문자열 17 = 166 bytes**다.
압축기나 자체 압축 해제 런타임은 없다. 이 크기는 검증한 도구 버전의 결과이며,
컴파일러/링커 버전에 따라 달라질 수 있다. 절대적인 최소 크기라는 증명은 아니다.

## 실행 호환성

**CPU 아키텍처만 같다고 실행을 보장하지 않는다.** 런타임에 libc/동적 로더가 필요하지
않으므로 glibc/musl 배포판의 차이에는 의존하지 않지만 다음 조건이 필요하다.

- **native Linux x86_64**의 ELF64/syscall/초기 스택 ABI. ARM, IA-32, macOS, Windows는 지원하지 않는다.
- 활성화되어 실제로 사용 가능한 **NX**, GNU_STACK 없는 ELF64에 대해 기본 비실행 스택을
  제공하는 커널 정책. 오래된/커스텀 커널은 별도 검증이 필요하다.
- 신뢰할 수 있는 `/usr/bin/sudo-rs`와 `/usr/bin/visudo-rs` 설치. 이 경로는 바꾸지 않는다.
  sudoedit는 백엔드의 이름 기반 편집 모드 계약에 의존한다.
- execve와 exit를 허용하는 실행 환경. seccomp, mount namespace, noexec 파일시스템,
  no_new_privs 또는 nosuid 정책은 실행이나 권한 상승을 제한할 수 있다.

CI는 Ubuntu 24.04 x86_64에서 비권한 픽스처를 검증한다. sudo-rs의 실제 인증·정책·권한
상승이나 모든 배포판/커널의 호환성을 보장하는 테스트는 아니다.

## CI 및 바이너리 배포

`.github/workflows/ci.yml`은 PR과 main push에서 다음을 수행한다.

1. 버전과 SHA-256을 고정한 공식 Zig 0.17.0 설치; Actions도 commit SHA로 고정한다.
2. Zig 포맷, shell 문법, 전체 wrapper/패키지 테스트 실행.
3. 재빌드 후 두 바이너리의 SHA-256 일치 확인.
4. 검증된 바이너리를 tar.gz로 묶어 Actions artifact로 업로드.

기본 workflow는 PR 코드를 secrets 없이 일반 runner 사용자로 테스트하며, 저장소 토큰
권한은 읽기만 허용한다. 기본 단계에서 sudo는 host test package 설치에만 사용한다.
실제 sudo-rs를 설치하거나 ptrace 정책을 완화하지 않는다. 다만 GitHub-hosted runner는
passwordless sudo가 가능한 일회성 환경이지, PR 코드에 대한 권한 제한 sandbox는 아니다.
민감한 자격 증명·사설 네트워크를 제공하거나 PR 산출물을 릴리스로 승격하지 않는다.

바이너리는 Git에 커밋하지 않고 [GitHub Releases](https://github.com/spi-ca/sudo-wrapper/releases)에
배포한다. **PR CI 통과 → 머지 → 해당 main commit CI 통과 → 태그/릴리스** 순서를 따른다.
릴리스 버전 형식은 `vyyyymmdd-1`이다. 같은 날짜의 후속 릴리스는 번호를 증가시킨다.
릴리스에는 해당 main CI가 생성한 artifact를 사용한다. artifact 이름만으로 고르지 않고,
저장소·push 이벤트·main 브랜치·병합 commit SHA·run 성공 상태를 모두 확인한다.

`./package.sh`는 이미 검증한 바이너리를 `zig-out/release/`에 포장한다.
패키징에는 GNU tar, gzip, SHA-256 도구와 Git(소스 commit 기록용)을 사용한다.
`SOURCE_COMMIT`으로 CI가 검증한 소스 commit을 기록할 수 있다.

- `sudo-wrapper-linux-x86_64.tar.gz`: `bin/sudo`, `bin/visudo`, **`bin/sudoedit -> sudo`**,
  README, MIT LICENSE, BUILD-INFO 및 내부 바이너리 SHA256SUMS.
- `SHA256SUMS`: tar.gz 전체의 SHA-256.

tar.gz를 사용해 실행 권한과 symlink를 보존한다. 파일/압축 메타데이터를 고정하므로
동일한 바이너리·문서·소스 commit·Zig 버전의 패키지는 동일한 바이트로 생성된다.
BUILD-INFO는 기록이지 서명이나 보안 증명이 아니며, SHA-256도 별도의 서명이 아니다.

다운로드 및 확인 예시:

```sh
gh release download --repo spi-ca/sudo-wrapper \
  --pattern 'sudo-wrapper-linux-x86_64.tar.gz' --pattern 'SHA256SUMS'
sha256sum --check --strict SHA256SUMS
tar -xzf sudo-wrapper-linux-x86_64.tar.gz
(cd sudo-wrapper-linux-x86_64 && sha256sum --check --strict SHA256SUMS)
ls -l sudo-wrapper-linux-x86_64/bin
```

자동 설치는 하지 않는다. 시스템 설치는 별도 단계에서 root 소유권, 0755,
신뢰할 수 있는 경로/대상과 기존 sudo 복구 경로를 확인한 뒤 수행해야 한다.

## ELF 보호

`link.ld`는 하나의 읽기/실행(비쓰기) LOAD 세그먼트만 지정한다. **GNU_STACK은 생략한다.**
표준 ELF64 ET_DYN이며 ASLR을 지원한다. 실제 주소 무작위화는 커널 설정에 따른다.
주소 획득은 상대 CALL/POP이므로 절대 주소·동적 로더·재배치 처리가 필요 없다.
쓰기 데이터/BSS/런타임 재배치가 추가되면 링크가 실패한다. 헤더와 코드를 겹치지 않는다.

스택 NX는 명시적인 GNU_STACK 선언이 아니라 **현대 NX 지원 Linux x86_64의 기본 동작**에
의존한다. 검증 환경은 `7.2.9-1-ari-svr-stable-git`이며, GNU_STACK 없는 ELF64의 실제
스택 매핑 `rw-p`를 확인했다. [Linux x86 ELF 코드](https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/elf.h)의
`elf_read_implies_exec` 설명에서도 이 경우는 `exec-none`이다.
**32비트 ELF/호환 실행, 오래된 커널 또는 다른 플랫폼에 이 보장을 적용하지 않는다.**
이식 시 매핑 검증을 다시 실행해야 하며, 기본 NX를 확인할 수 없는 환경에서는
GNU_STACK의 RW(비실행) 선언을 복원해야 한다. **NX가 지원될 뿐 아니라 활성화되어 실제로
사용 가능해야 한다.** `/proc/PID/maps`는 가상 메모리 권한을 보여 주며 하드웨어 NX 집행 자체를
증명하지는 않는다. NX가 비활성화되거나 사용 불가능한 환경은 지원하지 않으며,
GNU_STACK 복원만으로 그 문제를 해결할 수는 없다.
래퍼의 선언/생략은 exec 이후 sudo-rs/visudo-rs 자체의 스택 정책을 강제하지 않는다.

## 이름 선택과 보안 경계

검증한 설치본은 Arch `sudo-rs 0.2.15-1`이다. `/usr/bin/sudo-rs`와
`/usr/bin/sudoedit-rs`는 같은 inode의 root 소유 setuid 하드링크이고,
`/usr/bin/visudo-rs`는 별도의 root 소유 0755 실행 파일이다.

sudo-rs는 argv[0]의 basename이 `sudoedit`로 **시작하면** 편집 모드를 선택한다.
따라서 `sudoedit -> sudo` 링크로 편집 모드를 사용할 수 있다. 이 동작은
[공식 v0.2.15 CLI 소스](https://github.com/trifectatechfoundation/sudo-rs/blob/v0.2.15/src/sudo/cli/mod.rs)의
`is_sudoedit` 계약에 의존한다. 버전 업데이트 시 확인해야 한다.

**argv[0]은 호출자가 위조할 수 있다.** sudoedit 링크를 argv[0]="sudo"로 실행하면
일반 sudo 모드가 될 수 있고, 반대도 가능하다. 이것은 투명한 호환 별칭이며,
편집 모드만 강제하는 진입점이나 권한 경계가 아니다. sudo-rs는 선택된 작업에
대해 자체 인증과 정책을 적용해야 한다. 래퍼 경로/이름만 보고 제한적인 root
권한을 부여하는 sudoers 규칙이나 외부 privileged launcher를 구성하면 안 된다.

visudo는 별도 고정 대상으로 실행한다. argv[0]을 sudo로 위조해도 실행 대상은
visudo-rs에서 바뀌지 않는다. sudo의 alias로 visudo를 구현할 수는 없다.
visudo-rs는 자체적으로 setuid 설치를 거부하며, 일반 사용자의 실행만으로
권한이 상승하지 않는다. 보호된 sudoers 편집에는 별도 승인된 권한이 필요하다.

**보안 결함이 없다는 보장은 아니다.** 환경 필터링·인증·정책 집행·sudoedit의
파일 처리·권한 상승은 실행 대상의 책임이다.

- 모든 래퍼는 **일반 0755 파일**이다. setuid, setgid, file capability를 부여하지 않는다.
- 대상의 권한 설정은 배포판의 sudo-rs 패키지 정책에 따른다. visudo 대상은 비setuid다.
- 설치한 래퍼·대상·링크와 모든 상위 디렉터리는 일반 사용자가 수정·교체할 수 없게
  관리해야 한다. 빌드 디렉터리의 사용자 소유권은 시스템 설치용 소유권이 아니다.
- 대상이나 링크를 다시 래퍼로 연결하지 않는다. 재귀 탐지용 추가 syscall은 없다.
- 공격자가 관리하는 마운트 네임스페이스는 별도 신뢰 경계다. 절대 경로만으로
  실행 파일의 정체성을 인증하지는 못한다.
- 전달되는 환경과 열린 FD·신호 상태를 추가 검증하지 않는다.
- ptrace/strace는 setuid 권한 상승을 제한할 수 있다. 추적 결과는 권한 상승 검증이 아니다.

**자동 시스템 설치는 제공하지 않는다.** `/usr/bin` 등 시스템 파일은 변경하지 않는다.
설치에는 대상 준비, root 소유권·0755·신뢰할 수 있는 경로, 기존 sudo 복구 경로를
별도로 확인해야 한다. 이번 최적화/확장 검증은 비권한 픽스처에서 수행했다.

아키텍처는 Linux x86_64로 제한한다. 다른 플랫폼은 진입 스택 ABI, syscall 번호,
레지스터 규약과 ELF 구성을 별도로 검증해야 한다.
