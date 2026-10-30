// Test-only exact scalar decoder from frozen015 tbprobe.c.
static uint8_t *scalar_decompress_pairs(struct PairsData *d, size_t idx)
{
  if (!d->idxBits)
    return d->constValue;

  uint32_t mainIdx = (uint32_t)(idx >> d->idxBits);
  int litIdx = (idx & (((size_t)1 << d->idxBits) - 1)) - ((size_t)1 << (d->idxBits - 1));
  uint32_t block;
  memcpy(&block, d->indexTable + 6 * mainIdx, sizeof(block));
  block = from_le_u32(block);

  uint16_t idxOffset = *(uint16_t *)(d->indexTable + 6 * mainIdx + 4);
  litIdx += from_le_u16(idxOffset);

  if (litIdx < 0)
    while (litIdx < 0)
      litIdx += d->sizeTable[--block] + 1;
  else
    while (litIdx > d->sizeTable[block])
      litIdx -= d->sizeTable[block++] + 1;

  uint32_t *ptr = (uint32_t *)(d->data + ((size_t)block << d->blockSize));

  int m = d->minLen;
  uint16_t *offset = d->offset;
  uint64_t *base = d->base - m;
  uint8_t *symLen = d->symLen;
  uint32_t sym, bitCnt;

#ifdef DECOMP64
  uint64_t code = from_be_u64(*(uint64_t *)ptr);

  ptr += 2;
  bitCnt = 0; // number of "empty bits" in code
  for (;;) {
    int l = m;
    while (code < base[l]) l++;
    sym = from_le_u16(offset[l]);
    sym += (uint32_t)((code - base[l]) >> (64 - l));
    if (litIdx < (int)symLen[sym] + 1) break;
    litIdx -= (int)symLen[sym] + 1;
    code <<= l;
    bitCnt += l;
    if (bitCnt >= 32) {
      bitCnt -= 32;
      uint32_t tmp = from_be_u32(*ptr++);
      code |= (uint64_t)tmp << bitCnt;
    }
  }
#else
  uint32_t next = 0;
  uint32_t data = *ptr++;
  uint32_t code = from_be_u32(data);
  bitCnt = 0; // number of bits in next
  for (;;) {
    int l = m;
    while (code < base[l]) l++;
    sym = offset[l] + ((code - base[l]) >> (32 - l));
    if (litIdx < (int)symLen[sym] + 1) break;
    litIdx -= (int)symLen[sym] + 1;
    code <<= l;
    if (bitCnt < l) {
      if (bitCnt) {
	code |= (next >> (32 - l));
	l -= bitCnt;
      }
      data = *ptr++;
      next = from_be_u32(data);
      bitCnt = 32;
    }
    code |= (next >> (32 - l));
    next <<= l;
    bitCnt -= l;
  }
#endif
  uint8_t *symPat = d->symPat;
  while (symLen[sym] != 0) {
    uint8_t *w = symPat + (3 * sym);
    int s1 = ((w[1] & 0xf) << 8) | w[0];
    if (litIdx < (int)symLen[s1] + 1)
      sym = s1;
    else {
      litIdx -= (int)symLen[s1] + 1;
      sym = (w[2] << 4) | (w[1] >> 4);
    }
  }

  return &symPat[3 * sym];
}

