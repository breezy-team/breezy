#include <svn_auth.h>
int main(int argc, const char* arv[]) {
    svn_auth_provider_object_t* provider;
    apr_pool_t* pool;
    svn_auth_get_keychain_simple_provider(&provider, pool);
}
