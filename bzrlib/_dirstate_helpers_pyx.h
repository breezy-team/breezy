#ifndef _DIRSTATE_HELPERS_PYX_H
#define _DIRSTATE_HELPERS_PYX_H

/* for intptr_t */
#ifdef _MSC_VER
#include <io.h>
#else

#if defined(__SVR4) && defined(__sun)
#include <inttypes.h>
#else
#include <stdint.h>
#endif

#endif

#endif
