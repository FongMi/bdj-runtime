#include <jni.h>
#include <android/log.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef BDJ_JRE_ARCH
#error "Define BDJ_JRE_ARCH to the target JRE native library directory"
#endif

typedef jint (*create_vm_fn)(JavaVM **, void **, void *);

struct probe {
    const char *home;
    const char *jar;
    char result[2048];
    JavaVM *vm;
    int attached_ok;
};

static jlong echo(JNIEnv *env, jclass type, jlong value)
{
    (void) env;
    (void) type;
    return value;
}

static void *attach_worker(void *arg)
{
    struct probe *probe = arg;
    JNIEnv *env = NULL;
    if ((*probe->vm)->AttachCurrentThread(probe->vm, (void **) &env, NULL) != JNI_OK)
        return NULL;
    jclass type = (*env)->FindClass(env, "ZeroSmoke");
    jmethodID method = type ? (*env)->GetStaticMethodID(env, type, "attached", "()I") : NULL;
    if (method)
        probe->attached_ok = (*env)->CallStaticIntMethod(env, type, method) == 42
                && !(*env)->ExceptionCheck(env);
    if ((*env)->ExceptionCheck(env))
        (*env)->ExceptionDescribe(env);
    if ((*probe->vm)->DetachCurrentThread(probe->vm) != JNI_OK)
        probe->attached_ok = 0;
    return NULL;
}

static void *run_worker(void *arg)
{
    struct probe *probe = arg;
    char path[2048], classpath[2048], nativepath[2048];
    snprintf(path, sizeof(path), "%s/lib/" BDJ_JRE_ARCH "/server/libjvm.so", probe->home);
    setenv("JAVA_HOME", probe->home, 1);
    setenv("JDK_HOME", probe->home, 1);
    void *memory = malloc(1);
    if (!memory) {
        snprintf(probe->result, sizeof(probe->result), "FAIL malloc");
        return NULL;
    }
    uintptr_t pointer = (uintptr_t) memory;
    free(memory);
    unsigned long tag = 0;
#if UINTPTR_MAX > UINT32_MAX
    tag = (unsigned long) (pointer >> 56);
#endif
    __android_log_print(ANDROID_LOG_INFO, "BdjZero", "malloc=%#lx tag=%#lx",
            (unsigned long) pointer, tag);
    void *handle = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        snprintf(probe->result, sizeof(probe->result), "FAIL dlopen: %s", dlerror());
        return NULL;
    }
    create_vm_fn create = (create_vm_fn) dlsym(handle, "JNI_CreateJavaVM");
    if (!create) {
        snprintf(probe->result, sizeof(probe->result), "FAIL JNI_CreateJavaVM symbol");
        return NULL;
    }
    snprintf(classpath, sizeof(classpath), "-Djava.class.path=%s", probe->jar);
    snprintf(nativepath, sizeof(nativepath), "-Djava.library.path=%s/lib/" BDJ_JRE_ARCH, probe->home);
    JavaVMOption options[] = {
        {"-Xrs", NULL}, {"-Xint", NULL}, {"-Xmx64m", NULL},
        {"-Djava.awt.headless=true", NULL}, {classpath, NULL}, {nativepath, NULL}
    };
    JavaVMInitArgs args = {JNI_VERSION_1_8, 6, options, JNI_FALSE};
    JNIEnv *env = NULL;
    jint status = create(&probe->vm, (void **) &env, &args);
    if (status != JNI_OK) {
        snprintf(probe->result, sizeof(probe->result), "FAIL create JVM: %d", status);
        return NULL;
    }
    jclass type = (*env)->FindClass(env, "ZeroSmoke");
    JNINativeMethod callback = {"echo", "(J)J", (void *) echo};
    jmethodID run = NULL;
    if (type && (*env)->RegisterNatives(env, type, &callback, 1) == JNI_OK)
        run = (*env)->GetStaticMethodID(env, type, "run", "()Ljava/lang/String;");
    jstring result = run ? (*env)->CallStaticObjectMethod(env, type, run) : NULL;
    if ((*env)->ExceptionCheck(env) || !result) {
        (*env)->ExceptionDescribe(env);
        snprintf(probe->result, sizeof(probe->result), "FAIL class/JNI/GC/AWT probe");
    } else {
        const char *value = (*env)->GetStringUTFChars(env, result, NULL);
        if (!value) {
            if ((*env)->ExceptionCheck(env))
                (*env)->ExceptionDescribe(env);
            snprintf(probe->result, sizeof(probe->result), "FAIL JNI result string");
        } else {
            snprintf(probe->result, sizeof(probe->result), "PASS tag=%#lx; %s",
                    tag, value);
            (*env)->ReleaseStringUTFChars(env, result, value);
            pthread_t thread;
            if (pthread_create(&thread, NULL, attach_worker, probe) != 0) {
                snprintf(probe->result, sizeof(probe->result), "FAIL pthread_create");
            } else {
                pthread_join(thread, NULL);
                if (!probe->attached_ok)
                    snprintf(probe->result, sizeof(probe->result), "FAIL attach/detach callback");
            }
        }
    }
    status = (*probe->vm)->DestroyJavaVM(probe->vm);
    if (status != JNI_OK)
        snprintf(probe->result, sizeof(probe->result), "FAIL destroy JVM: %d", status);
    return NULL;
}

JNIEXPORT jstring JNICALL Java_com_fongmi_android_bdjzero_ProbeActivity_runProbe(
        JNIEnv *env, jclass type, jstring home, jstring jar)
{
    (void) type;
    struct probe probe = {0};
    probe.home = (*env)->GetStringUTFChars(env, home, NULL);
    if (!probe.home)
        return NULL;
    probe.jar = (*env)->GetStringUTFChars(env, jar, NULL);
    if (!probe.jar) {
        (*env)->ReleaseStringUTFChars(env, home, probe.home);
        return NULL;
    }
    pthread_t thread;
    if (pthread_create(&thread, NULL, run_worker, &probe) != 0) {
        snprintf(probe.result, sizeof(probe.result), "FAIL worker creation");
    } else {
        pthread_join(thread, NULL);
    }
    (*env)->ReleaseStringUTFChars(env, home, probe.home);
    (*env)->ReleaseStringUTFChars(env, jar, probe.jar);
    __android_log_print(ANDROID_LOG_INFO, "BdjZero", "%s", probe.result);
    return (*env)->NewStringUTF(env, probe.result);
}
