#!/bin/sh

cwd=$(pwd)

cd ${CK_ENV_BENCH_SYLT_TRACE_GENERATOR}

rm -f ./a.out

# Check C++ for Android
EXTRA="${CK_COMPILER_FLAG_CPP11}"
if [ "${CK_ENV_LIB_STDCPP_INCLUDE}" != "" ] ; then
  EXTRA="${EXTRA} ${CK_FLAG_PREFIX_INCLUDE}${CK_ENV_LIB_STDCPP_INCLUDE}"
fi
if [ "${CK_ENV_LIB_STDCPP_INCLUDE_EXTRA}" != "" ] ; then
  EXTRA="${EXTRA} ${CK_FLAG_PREFIX_INCLUDE}${CK_ENV_LIB_STDCPP_INCLUDE_EXTRA}"
fi

echo ""
echo "$CK_CXX ${EXTRA} $CK_COMPILER_FLAGS_OBLIGATORY $CK_FLAGS_DYNAMIC_BIN ${CK_FLAG_PREFIX_INCLUDE}./ demo.cc  ${CK_FLAGS_OUTPUT}a.out ${CK_ENV_LIB_STDCPP_STATIC}"
$CK_CXX ${EXTRA} $CK_COMPILER_FLAGS_OBLIGATORY $CK_FLAGS_DYNAMIC_BIN ${CK_FLAG_PREFIX_INCLUDE}./  demo.cc ${CK_FLAGS_OUTPUT}a.out ${CK_ENV_LIB_STDCPP_STATIC}
er=$?; if [ $er != 0 ]; then exit $er; fi

echo ""
cp -f ./a.out $cwd
