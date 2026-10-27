/* scfps.c - Silicon Coast : compteur d'images et télécommande pour BG:EE / BG2:EE sur Mac (MIT).
 *
 * Bibliothèque chargée au lancement du jeu par DYLD_INSERT_LIBRARIES (la signature du jeu l'autorise :
 * com.apple.security.cs.allow-dyld-environment-variables + disable-library-validation). Elle ne modifie aucun
 * fichier du jeu.
 *
 * 1. Mesure. La méthode -[NSOpenGLContext flushBuffer] est remplacée, dans le runtime Objective-C, par une fonction
 *    qui note l'instant de chaque image puis appelle l'originale. Les envois de textures (glTexImage2D,
 *    glTexSubImage2D, glCompressedTexImage2D) et les dessins (glDrawArrays) sont comptés par interposition dyld.
 *    Chaque seconde, une ligne CSV dans le fichier SCFPS_LOG (défaut /tmp/scfps.csv) :
 *      t_s, images, intervalle moyen et max (ms), CPU du fil de rendu par image (moyenne, max, ms), attente dans
 *      flushBuffer par image (ms), CPU du processus (% d'un coeur), mémoire résidente (Mo), envois de textures,
 *      Mo de textures envoyés, dessins par image, fenêtre visible (0/1), jeu au premier plan (0/1)
 *    L'App Nap de macOS est désactivé pendant la mesure (sinon un jeu caché peut être ralenti).
 * 2. Télécommande. Un fil lit le fichier cmd.txt posé à côté de la bibliothèque, l'efface, et exécute ses lignes
 *    dans l'ordre :
 *      move X Y | click X Y | dclick X Y | rclick X Y   souris, en points, origine en haut à gauche du contenu
 *      key CODE                                          touche (code clavier Mac : 53 Échap, 49 espace)
 *      sleep MS | mark TEXTE | info | exit
 *    Les événements souris sont remis directement à SDL, sur le fil principal, sans passer par la fenêtre active :
 *    le jeu n'a pas besoin d'être au premier plan. Compte rendu dans etat.txt, à côté de la bibliothèque.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <dlfcn.h>
#include <pthread.h>
#include <sys/time.h>
#include <sys/resource.h>
#include <mach/mach.h>
#include <mach/mach_time.h>

typedef void *ScId;
typedef void *ScSel;
typedef struct { double x, y; } ScPoint;
typedef struct { double x, y, w, h; } ScRect;

/* ---- runtime Objective-C et libdispatch, pris par dlsym (pas d'en-têtes Apple nécessaires) ---- */
static ScId (*p_getClass)(const char *);
static ScSel (*p_selReg)(const char *);
static void *(*p_getMethod)(ScId, ScSel);
static void *(*p_setImp)(void *, void *);
static const char *(*p_className)(ScId);
static void *(*p_poolPush)(void);
static void (*p_poolPop)(void *);
static void *p_msgSend;
static void (*p_async_f)(void *, void *, void (*)(void *));
static void *p_mainq;

#define SL(s) p_selReg(s)
static ScId m0(ScId o, const char *s) { return ((ScId (*)(ScId, ScSel))p_msgSend)(o, SL(s)); }
static ScId m1(ScId o, const char *s, ScId a) { return ((ScId (*)(ScId, ScSel, ScId))p_msgSend)(o, SL(s), a); }
static unsigned long mul(ScId o, const char *s) { return ((unsigned long (*)(ScId, ScSel))p_msgSend)(o, SL(s)); }
static double mdbl(ScId o, const char *s) { return ((double (*)(ScId, ScSel))p_msgSend)(o, SL(s)); }
static ScRect mrect(ScId o, const char *s) { return ((ScRect (*)(ScId, ScSel))p_msgSend)(o, SL(s)); }
static ScId midx(ScId o, unsigned long i) {
    return ((ScId (*)(ScId, ScSel, unsigned long))p_msgSend)(o, SL("objectAtIndex:"), i);
}
static ScId nsstr(const char *s) {
    return ((ScId (*)(ScId, ScSel, const char *))p_msgSend)(p_getClass("NSString"), SL("stringWithUTF8String:"), s);
}

/* ---- état de la mesure ---- */
static void (*orig_flush)(ScId, ScSel);
static FILE *out, *etat;
static char dir[1024];
static mach_timebase_info_data_t tb;
static double t0, t_prev, sec_start, th_prev, proc_prev;
static double ft_sum, ft_max, cpu_sum, cpu_max, wait_sum;
static int frames;
static volatile long tex_calls, tex_bytes, draw_calls;
static volatile int win_visible = -1, app_active = -1;
static volatile int flush_main = -1;

static double now_ms(void) { return (double)mach_absolute_time() * tb.numer / tb.denom / 1e6; }

static double thread_cpu_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

static double proc_cpu_ms(void) {
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
    return (ru.ru_utime.tv_sec + ru.ru_stime.tv_sec) * 1e3 + (ru.ru_utime.tv_usec + ru.ru_stime.tv_usec) / 1e3;
}

static double resident_mb(void) {
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t n = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &n) != KERN_SUCCESS) return -1;
    return info.resident_size / 1048576.0;
}

static void note(const char *fmt, const char *arg) {
    if (!etat) return;
    fprintf(etat, "%.1f ", (now_ms() - t0) / 1e3);
    fprintf(etat, fmt, arg);
    fputc('\n', etat);
    fflush(etat);
}

/* ---- télécommande : file de commandes exécutées sur le fil principal ---- */
#define QN 64
#define QL 160
static pthread_mutex_t qmu = PTHREAD_MUTEX_INITIALIZER;
static char q[QN][QL];
static int qh, qt;

static ScId sdl_window(void) {
    ScId app = m0(p_getClass("NSApplication"), "sharedApplication");
    ScId wins = app ? m0(app, "windows") : NULL;
    unsigned long n = wins ? mul(wins, "count") : 0;
    for (unsigned long i = 0; i < n; i++) {
        ScId w = midx(wins, i), d = m0(w, "delegate");
        if (d && strcmp(p_className(d), "Cocoa_WindowListener") == 0) return w;
    }
    return n ? midx(wins, 0) : NULL;
}

/* type NSEvent : 1 gauche enfoncé, 2 gauche relâché, 3 droit enfoncé, 4 droit relâché, 5 déplacement */
static void mouse(ScId win, unsigned long type, double x, double y, long clicks) {
    ScRect cr = mrect(m0(win, "contentView"), "frame");
    ScPoint p = { x, cr.h - y };
    long wn = (long)mul(win, "windowNumber");
    double ts = mdbl(m0(p_getClass("NSProcessInfo"), "processInfo"), "systemUptime");
    typedef ScId (*mk_t)(ScId, ScSel, unsigned long, ScPoint, unsigned long, double, long, ScId, long, long, float);
    ScId ev = ((mk_t)p_msgSend)(p_getClass("NSEvent"),
        SL("mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:"),
        type, p, 0, ts, wn, NULL, 0, clicks, (type == 1 || type == 3) ? 1.0f : 0.0f);
    const char *sel = type == 1 ? "mouseDown:" : type == 2 ? "mouseUp:" : type == 3 ? "rightMouseDown:"
                    : type == 4 ? "rightMouseUp:" : "mouseMoved:";
    ScId target = m0(win, "delegate");      /* Cocoa_WindowListener de SDL */
    if (target && ev) m1(target, sel, ev);
}

static void key(ScId win, unsigned short code, int down) {
    const char *c = code == 53 ? "\033" : code == 49 ? " " : code == 36 ? "\r" : code == 48 ? "\t" : "";
    ScId chars = nsstr(c);
    long wn = (long)mul(win, "windowNumber");
    double ts = mdbl(m0(p_getClass("NSProcessInfo"), "processInfo"), "systemUptime");
    typedef ScId (*kk_t)(ScId, ScSel, unsigned long, ScPoint, unsigned long, double, long, ScId, ScId, ScId, _Bool,
                         unsigned short);
    ScPoint p = { 0, 0 };
    ScId ev = ((kk_t)p_msgSend)(p_getClass("NSEvent"),
        SL("keyEventWithType:location:modifierFlags:timestamp:windowNumber:context:characters:"
           "charactersIgnoringModifiers:isARepeat:keyCode:"),
        down ? 10 : 11, p, 0, ts, wn, NULL, chars, chars, 0, code);
    ScId app = m0(p_getClass("NSApplication"), "sharedApplication");
    if (ev) ((void (*)(ScId, ScSel, ScId, _Bool))p_msgSend)(app, SL("postEvent:atStart:"), ev, 0);
}

static void exec_main(const char *line) {
    char c[16] = "";
    double x = 0, y = 0, k = 1;
    sscanf(line, "%15s %lf %lf %lf", c, &x, &y, &k);
    ScId win = sdl_window();
    if (!strcmp(c, "_vis")) {
        if (win) win_visible = (mul(win, "occlusionState") & 2) ? 1 : 0;
        ScId app = m0(p_getClass("NSApplication"), "sharedApplication");
        app_active = (mul(app, "isActive") & 0xff) ? 1 : 0;
        return;
    }
    if (!win) { note("erreur : pas de fenêtre (%s)", line); return; }
    if (!strcmp(c, "move")) mouse(win, 5, x, y, 0);
    else if (!strcmp(c, "down")) mouse(win, 1, x, y, (long)k);
    else if (!strcmp(c, "up")) mouse(win, 2, x, y, (long)k);
    else if (!strcmp(c, "rdown")) mouse(win, 3, x, y, 1);
    else if (!strcmp(c, "rup")) mouse(win, 4, x, y, 1);
    else if (!strcmp(c, "kdown")) key(win, (unsigned short)x, 1);
    else if (!strcmp(c, "kup")) key(win, (unsigned short)x, 0);
    else if (!strcmp(c, "info")) {
        ScRect f = mrect(win, "frame"), cr = mrect(m0(win, "contentView"), "frame");
        char b[400];
        snprintf(b, sizeof b, "fenêtre %.0fx%.0f à (%.0f,%.0f), contenu %.0fx%.0f, échelle %.1f, délégué %s, "
                 "fenêtre %s, rendu sur le fil principal %d, visible %d", f.w, f.h, f.x, f.y, cr.w, cr.h,
                 mdbl(win, "backingScaleFactor"), p_className(m0(win, "delegate")), p_className(win),
                 (int)flush_main, (int)((mul(win, "occlusionState") & 2) != 0));
        note("info %s", b);
        return;
    } else { note("erreur : commande inconnue (%s)", line); return; }
}

static void run_queue(void) {                    /* fil principal */
    for (;;) {
        char line[QL];
        pthread_mutex_lock(&qmu);
        if (qh == qt) { pthread_mutex_unlock(&qmu); return; }
        memcpy(line, q[qh % QN], QL);
        qh++;
        pthread_mutex_unlock(&qmu);
        void *pool = p_poolPush ? p_poolPush() : NULL;
        exec_main(line);
        if (pool) p_poolPop(pool);
    }
}
static void run_queue_cb(void *ctx) { (void)ctx; run_queue(); }

static int post_main(const char *line, int wait) {
    pthread_mutex_lock(&qmu);
    if (qt - qh >= QN) { pthread_mutex_unlock(&qmu); return 0; }
    snprintf(q[qt % QN], QL, "%s", line);
    qt++;
    pthread_mutex_unlock(&qmu);
    if (p_async_f && p_mainq) p_async_f(p_mainq, NULL, run_queue_cb);
    for (int i = 0; wait && i < 500; i++) {          /* 5 s au plus */
        pthread_mutex_lock(&qmu);
        int empty = qh == qt;
        pthread_mutex_unlock(&qmu);
        if (empty) return 1;
        usleep(10000);
    }
    return !wait;
}

static void run_line(char *line) {
    char c[16] = "", b[QL];
    double x = 0, y = 0;
    sscanf(line, "%15s %lf %lf", c, &x, &y);
    int ok = 1;
    if (!strcmp(c, "click") || !strcmp(c, "dclick") || !strcmp(c, "rclick")) {
        int right = c[0] == 'r';
        snprintf(b, QL, "move %.1f %.1f", x, y); ok &= post_main(b, 1);
        usleep(60000);
        snprintf(b, QL, "%s %.1f %.1f 1", right ? "rdown" : "down", x, y); ok &= post_main(b, 1);
        usleep(80000);
        snprintf(b, QL, "%s %.1f %.1f 1", right ? "rup" : "up", x, y); ok &= post_main(b, 1);
        if (c[0] == 'd') {
            usleep(80000);
            snprintf(b, QL, "down %.1f %.1f 2", x, y); ok &= post_main(b, 1);
            usleep(80000);
            snprintf(b, QL, "up %.1f %.1f 2", x, y); ok &= post_main(b, 1);
        }
    } else if (!strcmp(c, "key")) {
        snprintf(b, QL, "kdown %d", (int)x); ok &= post_main(b, 1);
        usleep(80000);
        snprintf(b, QL, "kup %d", (int)x); ok &= post_main(b, 1);
    } else if (!strcmp(c, "sleep")) {
        usleep((useconds_t)(x * 1000));
    } else if (!strcmp(c, "mark")) {
        if (out) { fprintf(out, "# mark %.1f %s\n", (now_ms() - t0) / 1e3, line + 5); fflush(out); }
    } else if (!strcmp(c, "exit")) {
        note("ok %s", line);
        if (out) { fprintf(out, "# exit %.1f\n", (now_ms() - t0) / 1e3); fflush(out); }
        _exit(0);
    } else {
        ok = post_main(line, 1);
    }
    note(ok ? "ok %s" : "délai dépassé : %s", line);
}

static void app_nap_off(void) {
    void *pool = p_poolPush ? p_poolPush() : NULL;
    ScId pi = m0(p_getClass("NSProcessInfo"), "processInfo");
    unsigned long long opts = (0x00FFFFFFULL & ~(1ULL << 20)) | 0xFF00000000ULL;  /* UserInitiated, LatencyCritical */
    ScId tok = ((ScId (*)(ScId, ScSel, unsigned long long, ScId))p_msgSend)(pi, SL("beginActivityWithOptions:reason:"),
                                                                              opts, nsstr("Silicon Coast : mesure"));
    if (tok) m0(tok, "retain");
    note("App Nap désactivé : %s", tok ? "oui" : "non");
    if (pool) p_poolPop(pool);
}

static void *control(void *arg) {
    (void)arg;
    char path[1100];
    snprintf(path, sizeof path, "%s/cmd.txt", dir);
    usleep(1500000);
    app_nap_off();
    for (int tick = 1;; tick++) {
        FILE *f = fopen(path, "r");
        if (f) {
            static char lines[QN][QL];
            int n = 0;
            while (n < QN && fgets(lines[n], QL, f)) {
                lines[n][strcspn(lines[n], "\r\n")] = 0;
                if (lines[n][0] && lines[n][0] != '#') n++;
            }
            fclose(f);
            unlink(path);
            for (int i = 0; i < n; i++) run_line(lines[i]);
        }
        usleep(100000);
        if (tick % 10 == 0) post_main("_vis", 0);
    }
    return NULL;
}

/* ---- comptage OpenGL par interposition ---- */
typedef unsigned int GLenum;
typedef int GLint;
typedef int GLsizei;
extern void glTexImage2D(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void *);
extern void glTexSubImage2D(GLenum, GLint, GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, const void *);
extern void glCompressedTexImage2D(GLenum, GLint, GLenum, GLsizei, GLsizei, GLint, GLsizei, const void *);
extern void glDrawArrays(GLenum, GLint, GLsizei);
extern const unsigned char *glGetString(GLenum);

static long bpp(GLenum format, GLenum type) {
    switch (type) {
    case 0x8033: case 0x8034: case 0x8363: case 0x8364: case 0x8365: case 0x8366: return 2;
    case 0x8035: case 0x8367: case 0x8368: return 4;
    }
    switch (format) {
    case 0x1903: case 0x1906: case 0x1909: return 1;
    case 0x190A: return 2;
    case 0x1907: return 3;
    default: return 4;
    }
}
static void sc_glTexImage2D(GLenum t, GLint l, GLint i, GLsizei w, GLsizei h, GLint b, GLenum f, GLenum ty,
                            const void *p) {
    tex_calls++;
    if (p) tex_bytes += (long)w * h * bpp(f, ty);
    glTexImage2D(t, l, i, w, h, b, f, ty, p);
}
static void sc_glTexSubImage2D(GLenum t, GLint l, GLint x, GLint y, GLsizei w, GLsizei h, GLenum f, GLenum ty,
                               const void *p) {
    tex_calls++;
    if (p) tex_bytes += (long)w * h * bpp(f, ty);
    glTexSubImage2D(t, l, x, y, w, h, f, ty, p);
}
static void sc_glCompressedTexImage2D(GLenum t, GLint l, GLenum i, GLsizei w, GLsizei h, GLint b, GLsizei n,
                                      const void *p) {
    tex_calls++;
    if (p) tex_bytes += n;
    glCompressedTexImage2D(t, l, i, w, h, b, n, p);
}
static void sc_glDrawArrays(GLenum m, GLint f, GLsizei c) {
    draw_calls++;
    glDrawArrays(m, f, c);
}
__attribute__((used, section("__DATA,__interpose"))) static const struct { const void *rep, *orig; } sc_interpose[] = {
    { (const void *)sc_glTexImage2D, (const void *)glTexImage2D },
    { (const void *)sc_glTexSubImage2D, (const void *)glTexSubImage2D },
    { (const void *)sc_glCompressedTexImage2D, (const void *)glCompressedTexImage2D },
    { (const void *)sc_glDrawArrays, (const void *)glDrawArrays },
};

/* ---- accroche sur flushBuffer ---- */
static void hooked_flush(ScId self, ScSel cmd) {
    double t = now_ms(), th = thread_cpu_ms();
    if (flush_main < 0) {
        flush_main = pthread_main_np();
        const unsigned char *r = glGetString(0x1F01), *v = glGetString(0x1F02);   /* GL_RENDERER, GL_VERSION */
        note("processeur graphique : %s", r ? (const char *)r : "?");
        note("OpenGL : %s", v ? (const char *)v : "?");
    }
    if (t_prev > 0) {
        double ft = t - t_prev, c = th - th_prev;
        ft_sum += ft; if (ft > ft_max) ft_max = ft;
        cpu_sum += c; if (c > cpu_max) cpu_max = c;
        frames++;
    }
    t_prev = t; th_prev = th;
    if (t - sec_start >= 1000.0 && frames > 0) {
        double pc = proc_cpu_ms();
        double pct = (pc - proc_prev) / (t - sec_start) * 100.0;
        long tc = tex_calls, tbytes = tex_bytes, dc = draw_calls;
        tex_calls = tex_bytes = draw_calls = 0;
        if (out) {
            fprintf(out, "%.1f,%d,%.2f,%.2f,%.2f,%.2f,%.2f,%.1f,%.0f,%ld,%.2f,%.0f,%d,%d\n", (t - t0) / 1e3, frames,
                    ft_sum / frames, ft_max, cpu_sum / frames, cpu_max, wait_sum / frames, pct, resident_mb(), tc,
                    tbytes / 1048576.0, (double)dc / frames, (int)win_visible, (int)app_active);
            fflush(out);
        }
        sec_start = t; proc_prev = pc;
        ft_sum = ft_max = cpu_sum = cpu_max = wait_sum = 0; frames = 0;
    }
    if (flush_main == 1) run_queue();
    double a = now_ms();
    orig_flush(self, cmd);
    wait_sum += now_ms() - a;
}

static int install(void) {
    ScId cls = p_getClass("NSOpenGLContext");
    if (!cls) return 0;
    void *m = p_getMethod(cls, SL("flushBuffer"));
    if (!m) return 0;
    orig_flush = (void (*)(ScId, ScSel))p_setImp(m, (void *)hooked_flush);
    return orig_flush != NULL;
}

static void *retry(void *arg) {
    (void)arg;
    for (int i = 0; i < 200; i++) {            /* 20 s au plus, le temps qu'AppKit soit chargé */
        if (install()) {
            if (out) { fprintf(out, "# accroche installée après %d essais\n", i + 1); fflush(out); }
            return NULL;
        }
        usleep(100000);
    }
    if (out) { fprintf(out, "# échec : NSOpenGLContext introuvable\n"); fflush(out); }
    return NULL;
}

__attribute__((constructor)) static void scfps_init(void) {
    mach_timebase_info(&tb);
    t0 = sec_start = now_ms();
    Dl_info di;
    if (dladdr((void *)scfps_init, &di) && di.dli_fname) {
        snprintf(dir, sizeof dir, "%s", di.dli_fname);
        char *s = strrchr(dir, '/');
        if (s) *s = 0; else snprintf(dir, sizeof dir, ".");
    } else snprintf(dir, sizeof dir, "/tmp");
    char p[1100];
    snprintf(p, sizeof p, "%s/etat.txt", dir);
    etat = fopen(p, "a");
    const char *path = getenv("SCFPS_LOG");
    out = fopen(path && *path ? path : "/tmp/scfps.csv", "a");
    if (out) {
        fprintf(out, "# scfps 2, pid %d\nt_s,images,intervalle_moy_ms,intervalle_max_ms,cpu_rendu_moy_ms,"
                     "cpu_rendu_max_ms,attente_flush_moy_ms,cpu_processus_pct,memoire_mo,textures_envois,"
                     "textures_mo,dessins_par_image,visible,actif\n", (int)getpid());
        fflush(out);
    }
    note("démarrage, journal %s", path && *path ? path : "/tmp/scfps.csv");
    void *objc = dlopen("/usr/lib/libobjc.A.dylib", RTLD_LAZY);
    if (!objc) return;
    p_getClass = (ScId (*)(const char *))dlsym(objc, "objc_getClass");
    p_selReg = (ScSel (*)(const char *))dlsym(objc, "sel_registerName");
    p_getMethod = (void *(*)(ScId, ScSel))dlsym(objc, "class_getInstanceMethod");
    p_setImp = (void *(*)(void *, void *))dlsym(objc, "method_setImplementation");
    p_className = (const char *(*)(ScId))dlsym(objc, "object_getClassName");
    p_poolPush = (void *(*)(void))dlsym(objc, "objc_autoreleasePoolPush");
    p_poolPop = (void (*)(void *))dlsym(objc, "objc_autoreleasePoolPop");
    p_msgSend = dlsym(objc, "objc_msgSend");
    p_async_f = (void (*)(void *, void *, void (*)(void *)))dlsym(RTLD_DEFAULT, "dispatch_async_f");
    p_mainq = dlsym(RTLD_DEFAULT, "_dispatch_main_q");
    if (!p_getClass || !p_selReg || !p_getMethod || !p_setImp || !p_className || !p_msgSend) return;
    proc_prev = proc_cpu_ms();
    pthread_t th;
    if (install()) {
        if (out) { fprintf(out, "# accroche installée au chargement\n"); fflush(out); }
    } else {
        pthread_create(&th, NULL, retry, NULL);
        pthread_detach(th);
    }
    pthread_create(&th, NULL, control, NULL);
    pthread_detach(th);
}
