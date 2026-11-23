/*
 * inttimem: read-only access to the INTTI game's memory, for the Ampumarata bot.
 *
 * Installed root-owned with only the CAP_SYS_PTRACE capability (no setuid), so the bot can
 * read the game process (another uid, in the Waydroid container) without general root:
 *   gcc -O2 -Wall -o inttimem inttimem.c
 *   sudo install -o root -g root -m 755 inttimem /usr/local/bin/inttimem
 *   sudo setcap cap_sys_ptrace+ep /usr/local/bin/inttimem
 *
 * It only ever reads, and only the process whose command line is exactly the INTTI package
 * (it finds the pid itself; no pid can be passed in). Commands on stdin, one per line:
 *   M                 the process's /proc/<pid>/maps, then a line "END"
 *   R <hexaddr> <n>   read n bytes (n <= 64 MiB): replies a 4-byte little-endian count, then
 *                     that many bytes (0 if the read failed)
 *   P                 the pid, as a line
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <unistd.h>

static const char PACKAGE[] = "com.OneGlitch.INTTI";
#define MAX_READ (64u << 20)

static pid_t find_game(void) {
    DIR *d = opendir("/proc");
    struct dirent *e;
    pid_t found = 0;
    if (!d) return 0;
    while ((e = readdir(d)) != NULL) {
        if (!isdigit((unsigned char)e->d_name[0])) continue;
        char path[300], cmd[256];
        snprintf(path, sizeof path, "/proc/%s/cmdline", e->d_name);
        FILE *f = fopen(path, "rb");
        if (!f) continue;
        size_t n = fread(cmd, 1, sizeof cmd - 1, f);
        fclose(f);
        cmd[n] = 0;   /* cmdline is NUL-separated: this compares argv[0] */
        if (strcmp(cmd, PACKAGE) == 0) {
            found = (pid_t)atoi(e->d_name);
            break;
        }
    }
    closedir(d);
    return found;
}

int main(void) {
    pid_t pid = find_game();
    if (!pid) {
        fprintf(stderr, "inttimem: %s is not running\n", PACKAGE);
        return 1;
    }
    char *buf = malloc(MAX_READ);
    if (!buf) return 1;
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        if (line[0] == 'P') {
            printf("%d\n", (int)pid);
        } else if (line[0] == 'M') {
            char path[64];
            snprintf(path, sizeof path, "/proc/%d/maps", (int)pid);
            FILE *f = fopen(path, "r");
            if (f) {
                size_t n;
                while ((n = fread(buf, 1, MAX_READ, f)) > 0) fwrite(buf, 1, n, stdout);
                fclose(f);
            }
            printf("END\n");
        } else if (line[0] == 'R') {
            unsigned long long addr = 0;
            unsigned int n = 0;
            uint32_t got = 0;
            if (sscanf(line + 1, "%llx %u", &addr, &n) == 2 && n <= MAX_READ) {
                struct iovec local = {buf, n}, remote = {(void *)(uintptr_t)addr, n};
                ssize_t r = process_vm_readv(pid, &local, 1, &remote, 1, 0);
                if (r > 0) got = (uint32_t)r;
            }
            fwrite(&got, 4, 1, stdout);
            if (got) fwrite(buf, 1, got, stdout);
        }
        fflush(stdout);
    }
    return 0;
}
