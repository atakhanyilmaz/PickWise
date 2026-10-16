#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
repo=external/job_shop_benchmark
commit=d088a26582f5cb79c6b4f2ad94f68ac7c50878cb
if [ ! -d "$repo/.git" ]; then
  git clone https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances.git "$repo"
fi
if [ -n "$(git -C "$repo" status --porcelain -- . ':(exclude)**/__pycache__/**')" ]; then
  echo 'Kaynak depoda yerel değişiklik var; işlem durduruldu.' >&2
  exit 1
fi
git -C "$repo" checkout --detach "$commit"
