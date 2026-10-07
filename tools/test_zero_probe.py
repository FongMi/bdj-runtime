"""Inject JNI string failures into the actual native probe without a JVM or device."""

import argparse
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


options = argparse.Namespace(cc=None, cflag=[], source=None)

JNI_HEADER = r"""
#ifndef BDJ_FAULT_JNI_H
#define BDJ_FAULT_JNI_H
#include <stdint.h>
typedef int jint;
typedef int64_t jlong;
typedef unsigned char jboolean;
typedef void *jclass;
typedef void *jstring;
typedef void *jobject;
typedef void *jmethodID;
typedef const struct JNINativeInterface_ *JNIEnv;
typedef const struct JNIInvokeInterface_ *JavaVM;
#define JNIEXPORT
#define JNICALL
#define JNI_OK 0
#define JNI_FALSE 0
#define JNI_VERSION_1_8 0x00010008
typedef struct { char *name; char *signature; void *fnPtr; } JNINativeMethod;
typedef struct { char *optionString; void *extraInfo; } JavaVMOption;
typedef struct { jint version; jint nOptions; JavaVMOption *options; jboolean ignoreUnrecognized; } JavaVMInitArgs;
struct JNINativeInterface_ {
  jclass (*FindClass)(JNIEnv *, const char *);
  jmethodID (*GetStaticMethodID)(JNIEnv *, jclass, const char *, const char *);
  jint (*CallStaticIntMethod)(JNIEnv *, jclass, jmethodID, ...);
  jboolean (*ExceptionCheck)(JNIEnv *);
  void (*ExceptionDescribe)(JNIEnv *);
  jint (*RegisterNatives)(JNIEnv *, jclass, const JNINativeMethod *, jint);
  jobject (*CallStaticObjectMethod)(JNIEnv *, jclass, jmethodID, ...);
  const char *(*GetStringUTFChars)(JNIEnv *, jstring, jboolean *);
  void (*ReleaseStringUTFChars)(JNIEnv *, jstring, const char *);
  jstring (*NewStringUTF)(JNIEnv *, const char *);
};
struct JNIInvokeInterface_ {
  jint (*AttachCurrentThread)(JavaVM *, void **, void *);
  jint (*DetachCurrentThread)(JavaVM *);
  jint (*DestroyJavaVM)(JavaVM *);
};
#endif
"""

FIXTURE = r"""
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <jni.h>
#include <pthread.h>
#define BDJ_JRE_ARCH "arm"
#define setenv probe_setenv
#include "PRODUCTION_SOURCE"
#undef assert
#define assert(condition) do { if (!(condition)) { \
  fprintf(stderr, "Assertion failed at line %d: %s\n", __LINE__, #condition); exit(1); \
} } while (0)

static int failure, gets, releases, null_releases, worker_calls, joins;
static int creates, destroys, attaches, detaches, described, pending_art, pending_zero;
static int acquired[4];
static char result_text[2048];
static JNIEnv art, zero;
static JavaVM vm;
static jstring string_id(int number) { return (jstring)(uintptr_t)number; }

static const char *get_utf(JNIEnv *env, jstring string, jboolean *copy) {
  (void)copy;
  int index = (int)(uintptr_t)string;
  gets++;
  if (index == failure) {
    if (env == &art) pending_art = 1; else pending_zero = 1;
    return NULL;
  }
  acquired[index]++;
  return index == 1 ? "candidate" : index == 2 ? "smoke.jar" :
      "OpenJDK Zero VM; logical font styles 20; JNI callback, class loading, GC, Java2D, fonts, PNG PASS";
}
static void release_utf(JNIEnv *env, jstring string, const char *value) {
  (void)env;
  int index = (int)(uintptr_t)string;
  if (!value) { null_releases++; return; }
  assert(acquired[index] == 1);
  acquired[index]--;
  releases++;
}
static jboolean exception_check(JNIEnv *env) { return env == &art ? pending_art : pending_zero; }
static void exception_describe(JNIEnv *env) {
  described++;
  if (env == &art) pending_art = 0; else pending_zero = 0;
}
static jclass find_class(JNIEnv *env, const char *name) {
  (void)env; assert(!strcmp(name, "ZeroSmoke")); return (jclass)1;
}
static jmethodID static_method(JNIEnv *env, jclass type, const char *name, const char *signature) {
  (void)env; (void)type; (void)name; (void)signature; return (jmethodID)1;
}
static jint static_int(JNIEnv *env, jclass type, jmethodID method, ...) {
  (void)env; (void)type; (void)method; return 42;
}
static jobject static_object(JNIEnv *env, jclass type, jmethodID method, ...) {
  (void)env; (void)type; (void)method; return string_id(3);
}
static jint register_natives(JNIEnv *env, jclass type, const JNINativeMethod *methods, jint count) {
  (void)env; (void)type; assert(count == 1 && !strcmp(methods[0].name, "echo")); return JNI_OK;
}
static jstring new_string(JNIEnv *env, const char *text) {
  assert(env == &art && !pending_art);
  snprintf(result_text, sizeof(result_text), "%s", text);
  return string_id(4);
}
static jint attach(JavaVM *machine, void **env, void *arguments) {
  (void)arguments; assert(machine == &vm); *env = &zero; attaches++; return JNI_OK;
}
static jint detach(JavaVM *machine) { assert(machine == &vm); detaches++; return JNI_OK; }
static jint destroy(JavaVM *machine) { assert(machine == &vm); destroys++; return JNI_OK; }
static jint create(JavaVM **machine, void **env, void *arguments) {
  JavaVMInitArgs *args = arguments;
  assert(args->version == JNI_VERSION_1_8 && args->nOptions == 6);
  *machine = &vm; *env = &zero; creates++; return JNI_OK;
}
int probe_setenv(const char *name, const char *value, int overwrite) {
  (void)name; (void)overwrite; assert(value != NULL); return 0;
}
void *dlopen(const char *name, int mode) { (void)name; (void)mode; return (void *)1; }
void *dlsym(void *handle, const char *name) {
  (void)handle; assert(!strcmp(name, "JNI_CreateJavaVM")); return (void *)create;
}
const char *dlerror(void) { return "injected error"; }
int __android_log_print(int priority, const char *tag, const char *format, ...) {
  (void)priority; (void)tag; (void)format; return 0;
}
int probe_pthread_create(pthread_t *thread, const void *attributes,
                         void *(*function)(void *), void *argument) {
  (void)attributes; *thread = 1; worker_calls++; function(argument); return 0;
}
int probe_pthread_join(pthread_t thread, void **result) { (void)thread; (void)result; joins++; return 0; }

int main(int argc, char **argv) {
  assert(argc == 2);
  failure = atoi(argv[1]);
  const struct JNINativeInterface_ interface = {
    find_class, static_method, static_int, exception_check, exception_describe,
    register_natives, static_object, get_utf, release_utf, new_string,
  };
  const struct JNIInvokeInterface_ invocation = {attach, detach, destroy};
  art = zero = &interface;
  vm = &invocation;
  jstring result = Java_com_fongmi_android_bdjzero_ProbeActivity_runProbe(
      &art, NULL, string_id(1), string_id(2));
  assert(null_releases == 0);
  for (int i = 1; i <= 3; i++) assert(acquired[i] == 0);
  if (failure <= 2 && failure > 0) {
    assert(result == NULL && pending_art && !pending_zero);
    assert(gets == failure && releases == failure - 1);
    assert(!worker_calls && !joins && !creates && !destroys && !attaches && !detaches && !described);
  } else if (failure == 3) {
    assert(result == string_id(4) && !pending_art && !pending_zero);
    assert(!strncmp(result_text, "FAIL ", 5));
    assert(gets == 3 && releases == 2 && worker_calls == 1 && joins == 1);
    assert(creates == 1 && destroys == 1 && !attaches && !detaches && described == 1);
  } else {
    assert(result == string_id(4) && !pending_art && !pending_zero);
    assert(!strncmp(result_text, "PASS tag=", 9) && strstr(result_text, "logical font styles 20;"));
    assert(gets == 3 && releases == 3 && worker_calls == 2 && joins == 2);
    assert(creates == 1 && destroys == 1 && attaches == 1 && detaches == 1 && !described);
  }
  puts("JNI string acquisition, pending exception and release ownership passed");
  return 0;
}
"""


class ZeroProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = options.cc or os.environ.get("CC") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("Pass --cc or set CC for the native host fault regression")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        root = pathlib.Path(cls.directory.name)
        (root / "android").mkdir()
        (root / "jni.h").write_text(JNI_HEADER, encoding="utf-8")
        (root / "android/log.h").write_text(
            "#define ANDROID_LOG_INFO 4\nint __android_log_print(int, const char *, const char *, ...);\n",
            encoding="utf-8",
        )
        (root / "dlfcn.h").write_text(
            "#define RTLD_NOW 2\n#define RTLD_GLOBAL 256\n"
            "void *dlopen(const char *, int);\nvoid *dlsym(void *, const char *);\n"
            "const char *dlerror(void);\n", encoding="utf-8",
        )
        (root / "pthread.h").write_text(
            "#pragma once\n#ifdef _WIN32\ntypedef unsigned long pthread_t;\n"
            "#else\n#include_next <pthread.h>\n#endif\n"
            "#define pthread_create probe_pthread_create\n#define pthread_join probe_pthread_join\n"
            "int probe_pthread_create(pthread_t *, const void *, void *(*)(void *), void *);\n"
            "int probe_pthread_join(pthread_t, void **);\n"
            "int probe_setenv(const char *, const char *, int);\n", encoding="utf-8",
        )
        production = options.source or pathlib.Path(__file__).with_name("zero_probe.c")
        fixture = root / "test.c"
        fixture.write_text(FIXTURE.replace("PRODUCTION_SOURCE", production.resolve().as_posix()), encoding="utf-8")
        cls.executable = root / ("test.exe" if os.name == "nt" else "test")
        subprocess.run(
            [compiler, *options.cflag, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(root),
             str(fixture), "-o", str(cls.executable)], check=True,
        )

    def run_fault(self, fault):
        result = subprocess.run([str(self.executable), str(fault)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_home_string_failure_preserves_pending_exception_without_starting_worker(self):
        self.run_fault(1)

    def test_jar_string_failure_releases_home_and_preserves_pending_exception(self):
        self.run_fault(2)

    def test_jvm_result_string_failure_reports_failure_and_destroys_vm(self):
        self.run_fault(3)

    def test_success_releases_each_string_once_and_attaches_detaches_destroys(self):
        self.run_fault(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc")
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--source", type=pathlib.Path)
    options, unittest_args = parser.parse_known_args()
    unittest.main(argv=[__file__, *unittest_args])
