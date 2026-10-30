/* MCHOSE K99 battery bridge daemon.
 *
 * Discovers the receiver's vendor hidraw interface, queries the battery
 * percentage, and re-publishes it through a UHID virtual Battery Strength
 * device so UPower / KDE Plasma can display it.
 */

#define _GNU_SOURCE
#include "hidraw.h"
#include "protocol.h"
#include "virtual_battery.h"

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/signalfd.h>
#include <sys/stat.h>
#include <sys/timerfd.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t g_should_exit = 0;
static int g_signal_pipe[2] = { -1, -1 };

static void on_signal(int signo)
{
    /* Async-signal-safe: write one byte to the self-pipe. */
    if (g_signal_pipe[1] >= 0) {
        unsigned char b = (unsigned char)signo;
        ssize_t r = write(g_signal_pipe[1], &b, 1);
        (void)r;
    }
    g_should_exit = 1;
}

static int install_signal_handlers(void)
{
    if (pipe(g_signal_pipe) < 0)
        return -1;
    int flags = fcntl(g_signal_pipe[0], F_GETFL, 0);
    fcntl(g_signal_pipe[0], F_SETFL, flags | O_NONBLOCK);
    fcntl(g_signal_pipe[0], F_SETFD, FD_CLOEXEC);
    fcntl(g_signal_pipe[1], F_SETFD, FD_CLOEXEC);

    struct sigaction sa = {
        .sa_handler = on_signal,
        .sa_flags = 0,
    };
    sigemptyset(&sa.sa_mask);
    if (sigaction(SIGINT, &sa, NULL) < 0)
        return -1;
    if (sigaction(SIGTERM, &sa, NULL) < 0)
        return -1;
    if (sigaction(SIGHUP, &sa, NULL) < 0)
        return -1;

    struct sigaction ign = { .sa_handler = SIG_IGN, .sa_flags = 0 };
    sigemptyset(&ign.sa_mask);
    sigaction(SIGPIPE, &ign, NULL);
    return 0;
}

static int run_query_and_publish(int hidraw_fd, int uhid_fd, bool raw,
                                 const device_profile *profile,
                                 int *last_pct, int *last_status)
{
    int pct = -1;
    uint8_t status = 0;
    int cksum_ok = 0;
    int rc = hidraw_query_battery(hidraw_fd, 5000, profile,
                                  &pct, &status, &cksum_ok);
    if (rc == 0) {
        if (raw) {
            fprintf(stderr,
                    "battery: %d%% status=0x%02x checksum=%s\n",
                    pct, status, cksum_ok ? "ok" : "BAD");
        }
        if (vb_send_percentage(uhid_fd, (uint8_t)pct) < 0)
            return -1;
        /* Per-profile charge-state mapping. Legacy K99 reads bits
         * 0x10/0x01; V3 returns 0 (discharging) for every input
         * because its charge semantics are unknown. */
        int charge_state = profile->charge_state(status);
        if (vb_send_status(uhid_fd, (uint8_t)charge_state) < 0)
            return -1;
        *last_pct = pct;
        *last_status = status;
        return 0;
    }
    if (rc == -2) {
        /* Timeout: keep last good value; never report 0% on comm error. */
        if (raw)
            fprintf(stderr, "battery: timeout, holding last value\n");
        return 0;
    }
    return -1;
}

static int run_once(bool raw, const char *explicit_device)
{
    const device_profile *profile = NULL;
    int hidraw_fd;
    if (explicit_device) {
        /* Try to identify the profile from sysfs so --device works
         * against both the legacy K99 vendor interface and the
         * K99 V3 boot-mouse interface. Fall back to the legacy
         * profile if nothing matches (preserves the historical
         * behaviour for paths that don't advertise a known VID/PID
         * through sysfs, e.g. when running as root inside a
         * container). */
        profile = hidraw_identify_profile(explicit_device);
        if (!profile)
            profile = mchose_profiles[0];
        hidraw_fd = hidraw_open(explicit_device);
        if (hidraw_fd < 0) {
            fprintf(stderr, "open %s: %s\n", explicit_device, strerror(errno));
            return 1;
        }
    } else {
        hidraw_target tgt;
        int rc = hidraw_discover(&tgt);
        if (rc < 0) {
            fprintf(stderr, "discovery failed\n");
            return 2;
        }
        if (raw)
            fprintf(stderr, "device: %s (profile=%s)\n",
                    tgt.path, tgt.profile ? tgt.profile->name : "?");
        profile = tgt.profile;
        hidraw_fd = hidraw_open(tgt.path);
        if (hidraw_fd < 0) {
            fprintf(stderr, "open %s: %s\n", tgt.path, strerror(errno));
            return 1;
        }
    }

    int pct = -1;
    uint8_t status = 0;
    int cksum_ok = 0;
    int rc = hidraw_query_battery(hidraw_fd, 5000, profile,
                                  &pct, &status, &cksum_ok);
    close(hidraw_fd);
    if (rc == 0) {
        if (raw) {
            fprintf(stderr, "battery: %d%% status=0x%02x checksum=%s\n",
                    pct, status, cksum_ok ? "ok" : "BAD");
        } else {
            printf("%d\n", pct);
        }
        return 0;
    }
    if (rc == -2) {
        fprintf(stderr, "battery: timeout\n");
    } else {
        fprintf(stderr, "battery: protocol error\n");
    }
    return 3;
}

static int run_daemon(int poll_seconds, bool raw)
{
    /* The UHID device is created lazily once we know which MCHOSE
     * device profile we matched; the legacy K99 profile is the
     * default so the daemon still boots cleanly on machines without
     * a receiver attached. */
    int uhid_fd = vb_open();
    if (uhid_fd < 0) {
        fprintf(stderr, "open /dev/uhid: %s\n", strerror(errno));
        return 1;
    }
    const device_profile *uhid_profile = NULL;

    sigset_t mask;
    sigemptyset(&mask);
    sigaddset(&mask, SIGINT);
    sigaddset(&mask, SIGTERM);
    sigaddset(&mask, SIGHUP);
    int signal_fd = signalfd(-1, &mask, SFD_CLOEXEC);
    if (signal_fd < 0) {
        fprintf(stderr, "signalfd: %s\n", strerror(errno));
        vb_destroy(uhid_fd);
        close(uhid_fd);
        return 1;
    }

    int timer_fd = timerfd_create(CLOCK_MONOTONIC, TFD_CLOEXEC);
    if (timer_fd < 0) {
        fprintf(stderr, "timerfd: %s\n", strerror(errno));
        close(g_signal_pipe[0]);
        close(g_signal_pipe[1]);
        vb_destroy(uhid_fd);
        close(uhid_fd);
        return 1;
    }
    struct itimerspec its = {
        .it_interval = { .tv_sec = poll_seconds, .tv_nsec = 0 },
        .it_value    = { .tv_sec = 0,             .tv_nsec = 1 },
    };
    if (timerfd_settime(timer_fd, 0, &its, NULL) < 0) {
        fprintf(stderr, "timerfd_settime: %s\n", strerror(errno));
        close(timer_fd);
        close(g_signal_pipe[0]);
        close(g_signal_pipe[1]);
        vb_destroy(uhid_fd);
        close(uhid_fd);
        return 1;
    }

    int hidraw_fd = -1;
    int last_pct = -1;
    int last_status = 0;

    for (;;) {
        if (g_should_exit)
            break;

        /* Try discovery if not currently connected. */
        if (hidraw_fd < 0) {
            hidraw_target tgt;
            int rc = hidraw_discover(&tgt);
            if (rc == 0) {
                hidraw_fd = hidraw_open(tgt.path);
                if (hidraw_fd < 0) {
                    if (raw)
                        fprintf(stderr, "hidraw open %s: %s\n",
                                tgt.path, strerror(errno));
                    hidraw_fd = -1;
                } else {
                    if (raw)
                        fprintf(stderr, "hidraw: opened %s (profile=%s)\n",
                                tgt.path,
                                tgt.profile ? tgt.profile->name : "?");
                    /* Lazily create the UHID virtual device using
                     * the matched profile's product id and name so
                     * DKMS can distinguish later generations. */
                    if (!uhid_profile && tgt.profile) {
                        if (vb_create(uhid_fd, tgt.profile->vb_product,
                                      tgt.profile->vb_name) < 0) {
                            close(hidraw_fd);
                            hidraw_fd = -1;
                        } else {
                            uhid_profile = tgt.profile;
                            if (raw)
                                fprintf(stderr,
                                        "uhid: created virtual battery "
                                        "(product=0x%04x name=\"%s\")\n",
                                        tgt.profile->vb_product,
                                        tgt.profile->vb_name);
                        }
                    }
                    if (hidraw_fd >= 0 && raw)
                        run_query_and_publish(hidraw_fd, uhid_fd, raw,
                                              uhid_profile,
                                              &last_pct, &last_status);
                }
            }
        }

        struct pollfd pfds[3] = {
            { .fd = g_signal_pipe[0], .events = POLLIN },
            { .fd = timer_fd,         .events = POLLIN },
            { .fd = uhid_fd,          .events = POLLIN },
        };

        int prc = poll(pfds, 3, 1000);
        if (prc < 0) {
            if (errno == EINTR)
                continue;
            fprintf(stderr, "poll: %s\n", strerror(errno));
            break;
        }

        if (pfds[0].revents & POLLIN) {
            unsigned char b;
            ssize_t n = read(g_signal_pipe[0], &b, 1);
            if (n == 1) {
                if (raw)
                    fprintf(stderr, "signal: %d (%s), exiting\n",
                            b, strsignal(b));
                break;
            }
        }

        if (pfds[1].revents & POLLIN) {
            uint64_t expirations;
            ssize_t n = read(timer_fd, &expirations, sizeof(expirations));
            (void)n;
            if (hidraw_fd >= 0) {
                int rc = run_query_and_publish(hidraw_fd, uhid_fd, raw,
                                               uhid_profile,
                                               &last_pct, &last_status);
                if (rc < 0) {
                    close(hidraw_fd);
                    hidraw_fd = -1;
                }
            } else {
                hidraw_target tgt;
                int rc = hidraw_discover(&tgt);
                if (rc == 0) {
                    hidraw_fd = hidraw_open(tgt.path);
                    if (hidraw_fd < 0)
                        hidraw_fd = -1;
                    else if (raw)
                        fprintf(stderr, "hidraw: reopened %s\n", tgt.path);
                }
            }
        }

        if (pfds[2].revents & POLLIN) {
            vb_drain_events(uhid_fd);
        }
    }

    if (hidraw_fd >= 0)
        close(hidraw_fd);
    vb_destroy(uhid_fd);
    close(uhid_fd);
    close(timer_fd);
    close(g_signal_pipe[0]);
    close(g_signal_pipe[1]);
    return 0;
}

static void usage(FILE *out)
{
    fprintf(out,
        "usage: mchose-k99-battery [options]\n"
        "  --once                  one-shot query, print percentage to stdout\n"
        "  --daemon                run as polling daemon with UHID output\n"
        "  --raw                   verbose logging to stderr\n"
        "  --device <path>         explicit /dev/hidrawN (default: auto)\n"
        "  --poll-seconds <int>    poll interval in daemon mode (default 300)\n"
        "  --help                  this help text\n");
}

int main(int argc, char **argv)
{
    if (install_signal_handlers() < 0) {
        fprintf(stderr, "sigaction: %s\n", strerror(errno));
        return 1;
    }

    bool as_once = false;
    bool as_daemon = false;
    bool raw = false;
    const char *device = NULL;
    int poll_seconds = 300;

    static const struct option longopts[] = {
        { "once",          no_argument,       0, '1' },
        { "daemon",        no_argument,       0, '2' },
        { "raw",           no_argument,       0, '3' },
        { "device",        required_argument, 0, '4' },
        { "poll-seconds",  required_argument, 0, '5' },
        { "help",          no_argument,       0, 'h' },
        { 0, 0, 0, 0 },
    };

    int c;
    while ((c = getopt_long(argc, argv, "", longopts, NULL)) != -1) {
        switch (c) {
        case '1': as_once = true; break;
        case '2': as_daemon = true; break;
        case '3': raw = true; break;
        case '4': device = optarg; break;
        case '5': poll_seconds = atoi(optarg); break;
        case 'h': usage(stdout); return 0;
        default:  usage(stderr); return 2;
        }
    }

    if (as_once)
        return run_once(raw, device);
    if (as_daemon)
        return run_daemon(poll_seconds, raw);

    /* Default: behave like --once for ergonomics. */
    return run_once(raw, device);
}
