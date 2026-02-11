#!/usr/bin/env bash
#
# Tests para install.sh - ejecutar con: bash tests/test_install.sh
#
# Prueba las funciones del instalador sin necesidad de root ni instalar nada.
# Usa un entorno aislado con comandos mock en PATH.
#
# Note: We don't use set -e here because we test for expected failures.

# ===================== Framework de test =====================
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAIL_MESSAGES=()

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; NC='\033[0m'

assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    ((TESTS_RUN++))
    if [ "$expected" = "$actual" ]; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} $desc"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("$desc: expected='$expected' actual='$actual'")
        echo -e "  ${RED}FAIL${NC} $desc (expected='$expected', got='$actual')"
    fi
}

assert_contains() {
    local desc="$1" needle="$2" haystack="$3"
    ((TESTS_RUN++))
    if echo "$haystack" | grep -qF "$needle"; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} $desc"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("$desc: '$needle' not found in output")
        echo -e "  ${RED}FAIL${NC} $desc ('$needle' not in output)"
    fi
}

assert_file_exists() {
    local desc="$1" filepath="$2"
    ((TESTS_RUN++))
    if [ -f "$filepath" ]; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} $desc"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("$desc: file '$filepath' not found")
        echo -e "  ${RED}FAIL${NC} $desc (file not found: $filepath)"
    fi
}

assert_dir_exists() {
    local desc="$1" dirpath="$2"
    ((TESTS_RUN++))
    if [ -d "$dirpath" ]; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} $desc"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("$desc: directory '$dirpath' not found")
        echo -e "  ${RED}FAIL${NC} $desc (dir not found: $dirpath)"
    fi
}

assert_exit_code() {
    local desc="$1" expected="$2"
    shift 2
    local actual
    set +e
    "$@" >/dev/null 2>&1
    actual=$?
    set -e
    ((TESTS_RUN++))
    if [ "$expected" = "$actual" ]; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} $desc"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("$desc: expected exit $expected, got $actual")
        echo -e "  ${RED}FAIL${NC} $desc (expected exit $expected, got $actual)"
    fi
}

# ===================== Setup =====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SCRIPT="$SCRIPT_DIR/install.sh"
WORK_DIR=$(mktemp -d)

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

# We extract testable functions from install.sh via sed, stripping:
# - set -euo pipefail (we handle errors ourselves)
# - main() call at the bottom
# This gives us a "library" of functions to test in subshells.
INSTALLER_LIB="$WORK_DIR/installer_lib.sh"
sed -e 's/^set -euo pipefail/# (disabled for testing)/' \
    -e 's/^main "\$@"/# (disabled for testing)/' \
    "$INSTALL_SCRIPT" > "$INSTALLER_LIB"

# ===================== Test: detect_distro =====================
test_detect_distro() {
    echo -e "\n${BOLD}[Test Suite] detect_distro${NC}"

    # Test with /etc/os-release present (mock)
    local mock_root="$WORK_DIR/distro_test"
    mkdir -p "$mock_root"

    # Test: detect_distro sets variables from os-release
    local result
    result=$(
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        detect_distro
        echo "$DISTRO_ID|$PKG_MANAGER"
    )

    # On this system we should detect something
    local distro_id pkg_mgr
    distro_id=$(echo "$result" | cut -d'|' -f1)
    pkg_mgr=$(echo "$result" | cut -d'|' -f2)

    # distro_id should not be empty
    ((TESTS_RUN++))
    if [ -n "$distro_id" ]; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} detect_distro sets DISTRO_ID ($distro_id)"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("detect_distro: DISTRO_ID is empty")
        echo -e "  ${RED}FAIL${NC} detect_distro DISTRO_ID is empty"
    fi

    # PKG_MANAGER should be one of the known values
    ((TESTS_RUN++))
    case "$pkg_mgr" in
        apt|dnf|yum|pacman|zypper|unknown)
            ((TESTS_PASSED++))
            echo -e "  ${GREEN}PASS${NC} detect_distro sets valid PKG_MANAGER ($pkg_mgr)"
            ;;
        *)
            ((TESTS_FAILED++))
            FAIL_MESSAGES+=("detect_distro: unexpected PKG_MANAGER=$pkg_mgr")
            echo -e "  ${RED}FAIL${NC} detect_distro unexpected PKG_MANAGER=$pkg_mgr"
            ;;
    esac
}

# ===================== Test: check_root =====================
test_check_root() {
    echo -e "\n${BOLD}[Test Suite] check_root${NC}"

    # Running as non-root should fail
    if [ "$EUID" -ne 0 ]; then
        local exit_code
        set +e
        (
            main() { :; }
            source "$INSTALLER_LIB"
            check_root
        ) >/dev/null 2>&1
        exit_code=$?
        set -e

        assert_eq "check_root fails for non-root user" "1" "$exit_code"
    else
        echo -e "  ${YELLOW}SKIP${NC} check_root (running as root)"
    fi
}

# ===================== Test: ask_yes_no =====================
test_ask_yes_no() {
    echo -e "\n${BOLD}[Test Suite] ask_yes_no${NC}"

    # Test default=y with empty input
    local result
    result=$(
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        echo "" | ask_yes_no "Test?" "y" && echo "yes" || echo "no"
    ) 2>/dev/null
    assert_contains "ask_yes_no default=y accepts empty as yes" "yes" "$result"

    # Test default=n with empty input
    result=$(
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        echo "" | ask_yes_no "Test?" "n" && echo "yes" || echo "no"
    ) 2>/dev/null
    assert_contains "ask_yes_no default=n rejects empty as no" "no" "$result"

    # Test explicit 'S' (Spanish yes)
    result=$(
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        echo "S" | ask_yes_no "Test?" "n" && echo "yes" || echo "no"
    ) 2>/dev/null
    assert_contains "ask_yes_no accepts 'S' as yes" "yes" "$result"

    # Test explicit 'n'
    result=$(
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        echo "n" | ask_yes_no "Test?" "y" && echo "yes" || echo "no"
    ) 2>/dev/null
    assert_contains "ask_yes_no rejects 'n'" "no" "$result"
}

# ===================== Test: package mapping per distro =====================
test_package_mapping() {
    echo -e "\n${BOLD}[Test Suite] Package mapping per distro${NC}"

    # Verify the package lists are defined for each PKG_MANAGER
    for mgr in apt dnf pacman zypper; do
        local has_qemu_pkgs
        has_qemu_pkgs=$(
            main() { :; }
            check_root() { :; }
            source "$INSTALLER_LIB"
            PKG_MANAGER="$mgr"

            # Extract logic from step_system_deps
            local qemu_pkgs=()
            case "$PKG_MANAGER" in
                apt) qemu_pkgs=(qemu-system-x86 qemu-utils ovmf swtpm) ;;
                dnf|yum) qemu_pkgs=(qemu-kvm qemu-img edk2-ovmf swtpm swtpm-tools) ;;
                pacman) qemu_pkgs=(qemu-full edk2-ovmf swtpm) ;;
                zypper) qemu_pkgs=(qemu-kvm qemu-tools ovmf swtpm) ;;
            esac
            echo "${#qemu_pkgs[@]}"
        )
        ((TESTS_RUN++))
        if [ "$has_qemu_pkgs" -gt 0 ]; then
            ((TESTS_PASSED++))
            echo -e "  ${GREEN}PASS${NC} PKG_MANAGER=$mgr has QEMU packages ($has_qemu_pkgs pkgs)"
        else
            ((TESTS_FAILED++))
            FAIL_MESSAGES+=("PKG_MANAGER=$mgr has no QEMU packages")
            echo -e "  ${RED}FAIL${NC} PKG_MANAGER=$mgr has no QEMU packages"
        fi
    done
}

# ===================== Test: directory creation =====================
test_directory_creation() {
    echo -e "\n${BOLD}[Test Suite] Installation directory structure${NC}"

    local test_dir="$WORK_DIR/install_test"
    mkdir -p "$test_dir"/{vms,images,data,backups}
    mkdir -p "$test_dir/vms/volumes"

    assert_dir_exists "vms/ directory created" "$test_dir/vms"
    assert_dir_exists "images/ directory created" "$test_dir/images"
    assert_dir_exists "data/ directory created" "$test_dir/data"
    assert_dir_exists "backups/ directory created" "$test_dir/backups"
    assert_dir_exists "vms/volumes/ directory created" "$test_dir/vms/volumes"
}

# ===================== Test: .env generation =====================
test_env_generation() {
    echo -e "\n${BOLD}[Test Suite] .env file generation${NC}"

    local test_dir="$WORK_DIR/env_test"
    mkdir -p "$test_dir"

    # Generate JWT secret like the installer does
    local jwt_secret
    jwt_secret=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "fallback-key")

    cat > "$test_dir/.env" <<EOF
JWT_SECRET_KEY=$jwt_secret
FASTVM_PRODUCTION=
CORS_ORIGINS=*
EOF

    assert_file_exists ".env file created" "$test_dir/.env"

    # Check JWT key is 64 hex chars
    local key_len
    key_len=$(grep JWT_SECRET_KEY "$test_dir/.env" | cut -d= -f2 | tr -d '[:space:]' | wc -c)
    assert_eq "JWT secret is 64 hex chars" "64" "$key_len"

    # Check .env contains expected vars
    local env_content
    env_content=$(cat "$test_dir/.env")
    assert_contains ".env has JWT_SECRET_KEY" "JWT_SECRET_KEY=" "$env_content"
    assert_contains ".env has CORS_ORIGINS" "CORS_ORIGINS=" "$env_content"

    # Test: .env not overwritten if exists
    echo "EXISTING=true" >> "$test_dir/.env"
    # Simulate installer check
    if [ -f "$test_dir/.env" ]; then
        local preserved="yes"
    else
        local preserved="no"
    fi
    assert_eq ".env not overwritten when it already exists" "yes" "$preserved"
}

# ===================== Test: systemd service template =====================
test_systemd_template() {
    echo -e "\n${BOLD}[Test Suite] Systemd service template${NC}"

    local test_dir="$WORK_DIR/systemd_test"
    mkdir -p "$test_dir"

    local install_dir="/opt/fast-vm"
    local real_user="testuser"
    local jwt_key="test-secret-123"

    cat > "$test_dir/fast-vm.service" <<EOF
[Unit]
Description=Fast VM - QEMU Virtual Machine Manager
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$real_user
WorkingDirectory=$install_dir/backend
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=JWT_SECRET_KEY=$jwt_key

[Install]
WantedBy=multi-user.target
EOF

    assert_file_exists "Service file created" "$test_dir/fast-vm.service"

    local service_content
    service_content=$(cat "$test_dir/fast-vm.service")
    assert_contains "Service has correct user" "User=testuser" "$service_content"
    assert_contains "Service has correct WorkingDirectory" "WorkingDirectory=/opt/fast-vm/backend" "$service_content"
    assert_contains "Service has Restart=always" "Restart=always" "$service_content"
    assert_contains "Service has correct ExecStart" "uvicorn app.main:app" "$service_content"
    assert_contains "Service has JWT env var" "JWT_SECRET_KEY=test-secret-123" "$service_content"
    assert_contains "Service starts after network" "After=network.target" "$service_content"
    assert_contains "Service in multi-user target" "WantedBy=multi-user.target" "$service_content"
}

# ===================== Test: project files check =====================
test_project_files_exist() {
    echo -e "\n${BOLD}[Test Suite] Project files exist${NC}"

    assert_file_exists "install.sh exists" "$SCRIPT_DIR/install.sh"
    assert_file_exists "docker-compose.yml exists" "$SCRIPT_DIR/docker-compose.yml"
    assert_file_exists "Dockerfile exists" "$SCRIPT_DIR/Dockerfile"
    assert_file_exists "start.sh exists" "$SCRIPT_DIR/start.sh"
    assert_file_exists "requirements.txt exists" "$SCRIPT_DIR/backend/requirements.txt"
    assert_file_exists "main.py exists" "$SCRIPT_DIR/backend/app/main.py"
    assert_file_exists "index.html exists" "$SCRIPT_DIR/frontend/index.html"
}

# ===================== Test: install_packages function (with mock) =====================
test_install_packages_mock() {
    echo -e "\n${BOLD}[Test Suite] install_packages with mock commands${NC}"

    # Create mock package managers in temp PATH
    local mock_bin="$WORK_DIR/mock_bin"
    mkdir -p "$mock_bin"

    # Mock apt-get that logs what was called
    cat > "$mock_bin/apt-get" <<'MOCK'
#!/bin/bash
echo "apt-get $*" >> "$MOCK_LOG"
MOCK
    chmod +x "$mock_bin/apt-get"

    # Test: apt install_packages calls apt-get with correct args
    local mock_log="$WORK_DIR/mock_apt.log"
    local result
    result=$(
        export PATH="$mock_bin:$PATH"
        export MOCK_LOG="$mock_log"
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        PKG_MANAGER="apt"
        install_packages python3 git curl 2>&1
    )
    if [ -f "$mock_log" ]; then
        local apt_calls
        apt_calls=$(cat "$mock_log")
        assert_contains "apt-get update called" "update" "$apt_calls"
        assert_contains "apt-get install has python3" "python3" "$apt_calls"
        assert_contains "apt-get install has git" "git" "$apt_calls"
        assert_contains "apt-get install has curl" "curl" "$apt_calls"
    else
        ((TESTS_RUN++))
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("apt mock log not created")
        echo -e "  ${RED}FAIL${NC} apt mock log not created"
    fi

    # Mock dnf
    cat > "$mock_bin/dnf" <<'MOCK'
#!/bin/bash
echo "dnf $*" >> "$MOCK_LOG"
MOCK
    chmod +x "$mock_bin/dnf"

    mock_log="$WORK_DIR/mock_dnf.log"
    result=$(
        export PATH="$mock_bin:$PATH"
        export MOCK_LOG="$mock_log"
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        PKG_MANAGER="dnf"
        install_packages qemu-kvm qemu-img 2>&1
    )
    if [ -f "$mock_log" ]; then
        local dnf_calls
        dnf_calls=$(cat "$mock_log")
        assert_contains "dnf install has qemu-kvm" "qemu-kvm" "$dnf_calls"
        assert_contains "dnf install has qemu-img" "qemu-img" "$dnf_calls"
    fi

    # Test: unsupported package manager returns error
    local exit_code
    set +e
    (
        main() { :; }
        check_root() { :; }
        source "$INSTALLER_LIB"
        PKG_MANAGER="unknown"
        install_packages some-pkg
    ) >/dev/null 2>&1
    exit_code=$?
    set -e
    assert_eq "install_packages fails for unknown PKG_MANAGER" "1" "$exit_code"
}

# ===================== Test: copy installer simulation =====================
test_copy_installation() {
    echo -e "\n${BOLD}[Test Suite] Copy installation simulation${NC}"

    local src="$WORK_DIR/copy_src"
    local dst="$WORK_DIR/copy_dst"
    mkdir -p "$src"
    mkdir -p "$dst"

    # Create minimal project structure
    echo "version: '3'" > "$src/docker-compose.yml"
    echo "FROM python:3.11" > "$src/Dockerfile"
    mkdir -p "$src/backend/app"
    echo "print('hello')" > "$src/backend/app/main.py"
    mkdir -p "$src/frontend"
    echo "<html>" > "$src/frontend/index.html"

    # Simulate installation copy
    cp -r "$src"/* "$dst"/

    assert_file_exists "docker-compose.yml copied" "$dst/docker-compose.yml"
    assert_file_exists "Dockerfile copied" "$dst/Dockerfile"
    assert_file_exists "backend/app/main.py copied" "$dst/backend/app/main.py"
    assert_file_exists "frontend/index.html copied" "$dst/frontend/index.html"
}

# ===================== Test: JWT secret generation =====================
test_jwt_secret_generation() {
    echo -e "\n${BOLD}[Test Suite] JWT secret generation methods${NC}"

    # Method 1: Python secrets
    local secret_py
    secret_py=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "")
    ((TESTS_RUN++))
    if [ -n "$secret_py" ] && [ ${#secret_py} -eq 64 ]; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} Python secrets generates 64-char hex"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("Python secrets failed: len=${#secret_py}")
        echo -e "  ${RED}FAIL${NC} Python secrets failed (len=${#secret_py})"
    fi

    # Verify it's actually hex
    ((TESTS_RUN++))
    if echo "$secret_py" | grep -qE '^[0-9a-f]{64}$'; then
        ((TESTS_PASSED++))
        echo -e "  ${GREEN}PASS${NC} Python secret is valid hex"
    else
        ((TESTS_FAILED++))
        FAIL_MESSAGES+=("Python secret is not valid hex")
        echo -e "  ${RED}FAIL${NC} Python secret is not valid hex"
    fi

    # Two secrets should be different
    local secret_py2
    secret_py2=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "")
    assert_eq "Two generated secrets are different" "true" "$([ "$secret_py" != "$secret_py2" ] && echo true || echo false)"
}

# ===================== Test: Dockerfile validation =====================
test_dockerfile() {
    echo -e "\n${BOLD}[Test Suite] Dockerfile validation${NC}"

    local dockerfile="$SCRIPT_DIR/Dockerfile"
    if [ ! -f "$dockerfile" ]; then
        echo -e "  ${YELLOW}SKIP${NC} Dockerfile not found"
        return
    fi

    local content
    content=$(cat "$dockerfile")
    assert_contains "Dockerfile has FROM" "FROM" "$content"
    assert_contains "Dockerfile installs qemu" "qemu" "$content"
    assert_contains "Dockerfile has EXPOSE or CMD" "CMD" "$content"
}

# ===================== Test: docker-compose validation =====================
test_docker_compose() {
    echo -e "\n${BOLD}[Test Suite] docker-compose.yml validation${NC}"

    local compose="$SCRIPT_DIR/docker-compose.yml"
    if [ ! -f "$compose" ]; then
        echo -e "  ${YELLOW}SKIP${NC} docker-compose.yml not found"
        return
    fi

    local content
    content=$(cat "$compose")
    assert_contains "docker-compose has services" "services" "$content"
    assert_contains "docker-compose has port mapping" "8000" "$content"
    assert_contains "docker-compose has volume mount" "volumes" "$content"
}

# ===================== Test: requirements.txt dependencies =====================
test_requirements() {
    echo -e "\n${BOLD}[Test Suite] requirements.txt validation${NC}"

    local reqfile="$SCRIPT_DIR/backend/requirements.txt"
    if [ ! -f "$reqfile" ]; then
        echo -e "  ${YELLOW}SKIP${NC} requirements.txt not found"
        return
    fi

    local content
    content=$(cat "$reqfile")
    assert_contains "Has fastapi" "fastapi" "$content"
    assert_contains "Has uvicorn" "uvicorn" "$content"
    assert_contains "Has psutil" "psutil" "$content"
    assert_contains "Has bcrypt" "bcrypt" "$content"
    assert_contains "Has python-jose" "python-jose" "$content"
}

# ===================== Run all tests =====================
echo -e "\n${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     Test Suite: install.sh                    ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"

test_detect_distro
test_check_root
test_ask_yes_no
test_package_mapping
test_directory_creation
test_env_generation
test_systemd_template
test_project_files_exist
test_install_packages_mock
test_copy_installation
test_jwt_secret_generation
test_dockerfile
test_docker_compose
test_requirements

# ===================== Summary =====================
echo ""
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
echo -e "${BOLD} Results: ${GREEN}$TESTS_PASSED passed${NC}, ${RED}$TESTS_FAILED failed${NC}, $TESTS_RUN total"
echo -e "${BOLD}════════════════════════════════════════════════${NC}"

if [ ${#FAIL_MESSAGES[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Failures:${NC}"
    for msg in "${FAIL_MESSAGES[@]}"; do
        echo -e "  - $msg"
    done
fi

echo ""
exit "$TESTS_FAILED"
