"""Fast Kronos inference with a KV cache, built on the original weights/modules from the Kronos repo.

Differences from model.kronos.auto_regressive_inference:
  * KV cache: the context is encoded once per point, each forecast step costs one token, not a full window.
  * Context is prefilled once per point and then shared by all samples.
  * Returns ALL samples (the original averages them away), so the spread can be used as a confidence measure.
  * s2_fix=True: in decode_s2 the original applies RoPE with the query length (=1) to the keys as well,
    so at inference every key gets position 0, while at training q/k positions are aligned (causal).
    s2_fix=True rotates keys/query with their true positions, as in training.
Requires context_len + pred_len <= max_context (no window rolling).
"""
import os
import sys
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vendor", "kronos"))
from model import Kronos, KronosTokenizer  # noqa: E402
from model.kronos import top_k_top_p_filtering, calc_time_stamps  # noqa: E402

HF_CACHE = os.environ.get("HF_HOME_CACHE")  # None -> default Hugging Face cache
MODELS = {
    "mini": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k", 2048),
    "small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base", 512),
    "base": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base", 512),
}


def load(name, model_path=None, tok_path=None):
    mid, tid, ctx = MODELS[name]
    tok = KronosTokenizer.from_pretrained(tok_path or tid, cache_dir=HF_CACHE).eval()
    model = Kronos.from_pretrained(model_path or mid, cache_dir=HF_CACHE).eval()
    return tok, model, ctx


def _rope(rot, x, pos):
    """Apply rotary embedding of module `rot` to x [B,H,T,D] at absolute positions pos (1-D LongTensor)."""
    t = pos.type_as(rot.inv_freq)
    freqs = torch.einsum("i,j->ij", t, rot.inv_freq)
    emb = torch.cat((freqs, freqs), dim=-1)
    cos, sin = emb.cos()[None, None], emb.sin()[None, None]
    x1, x2 = x.chunk(2, dim=-1)
    return x * cos + torch.cat((-x2, x1), dim=-1) * sin


def _append(cache, k, v):
    """Write k/v [B,h,T,d] into a preallocated cache (size cache['cap']); returns views of the filled part."""
    T = k.shape[2]
    if "k" not in cache:
        B, h, _, d = k.shape
        cap = max(cache.get("cap", T), T)
        cache["k"] = k.new_empty(B, h, cap, d)
        cache["v"] = v.new_empty(B, h, cap, d)
        cache["n"] = 0
    C = cache["n"]
    cache["k"][:, :, C:C + T] = k
    cache["v"][:, :, C:C + T] = v
    cache["n"] = C + T
    return cache["k"][:, :, :C + T], cache["v"][:, :, :C + T], C


def _expand(cache, S):
    cache["k"] = cache["k"].repeat_interleave(S, 0)
    cache["v"] = cache["v"].repeat_interleave(S, 0)


def _sample(logits, T, top_k, top_p):
    logits = logits / T
    if top_k > 0 or top_p < 1.0:
        logits = top_k_top_p_filtering(logits, top_k=top_k, top_p=top_p)
    return torch.multinomial(F.softmax(logits, dim=-1), 1).squeeze(-1)


class FastKronos:
    def __init__(self, tok, model, max_context=512, clip=5.0, s2_fix=False):
        self.tok, self.m, self.max_context, self.clip, self.s2_fix = tok, model, max_context, clip, s2_fix

    # ---- transformer pieces -------------------------------------------------
    def _block(self, blk, x, cache, pos):
        """One TransformerBlock over new tokens x [B,T,d] at positions pos, with KV cache dict."""
        a = blk.self_attn
        B, T, _ = x.shape
        h = blk.norm1(x)
        q = a.q_proj(h).view(B, T, a.n_heads, a.head_dim).transpose(1, 2)
        k = a.k_proj(h).view(B, T, a.n_heads, a.head_dim).transpose(1, 2)
        v = a.v_proj(h).view(B, T, a.n_heads, a.head_dim).transpose(1, 2)
        q, k = _rope(a.rotary, q, pos), _rope(a.rotary, k, pos)
        k, v, C = _append(cache, k, v)
        if T == 1:
            o = F.scaled_dot_product_attention(q, k, v)
        elif C == 0:
            o = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        else:  # new tokens see the whole cache + causal among themselves
            mask = torch.ones(T, C + T, dtype=torch.bool).tril(C)
            o = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        x = x + a.out_proj(o.transpose(1, 2).reshape(B, T, a.d_model))
        return x + blk.ffn(blk.norm2(x))

    def _forward(self, s1, s2, stamp, caches, start):
        m = self.m
        x = m.embedding([s1, s2]) + m.time_emb(stamp)
        pos = torch.arange(start, start + s1.shape[1])
        for blk, c in zip(m.transformer, caches):
            x = self._block(blk, x, c, pos)
        return m.norm(x)

    def _dep_kv(self, h, start, dc):
        """Append dependency-layer keys/values for new hidden states h [B,T,d] at positions start.."""
        ca = self.m.dep_layer.cross_attn
        B, T, _ = h.shape
        k = ca.k_proj(h).view(B, T, ca.n_heads, ca.head_dim).transpose(1, 2)
        v = ca.v_proj(h).view(B, T, ca.n_heads, ca.head_dim).transpose(1, 2)
        if self.s2_fix:   # training-consistent: keys rotated with their true positions
            k = _rope(ca.rotary, k, torch.arange(start, start + T))
        # original code: rotation at position 0 == identity
        _append(dc, k, v)

    def _s2_logits(self, h_last, s1_new, dc):
        m = self.m
        ca = m.dep_layer.cross_attn
        B = h_last.shape[0]
        L = dc["n"]
        sib = m.embedding.emb_s1(s1_new)[:, None, :]
        q = ca.q_proj(sib).view(B, 1, ca.n_heads, ca.head_dim).transpose(1, 2)
        if self.s2_fix:
            q = _rope(ca.rotary, q, torch.tensor([L - 1]))
        k, v = dc["k"][:, :, :L], dc["v"][:, :, :L]
        o = F.scaled_dot_product_attention(q, k, v)
        o = ca.out_proj(o.transpose(1, 2).reshape(B, 1, ca.d_model))
        x2 = m.dep_layer.norm(h_last[:, None, :] + o)
        return m.head.cond_forward(x2)[:, 0]

    # ---- main ---------------------------------------------------------------
    @torch.no_grad()
    def generate(self, x, x_stamp, y_stamp, pred_len, S=16, T=1.0, top_k=0, top_p=0.9):
        """x: [P,L,6] normalized float32, x_stamp [P,L,5], y_stamp [P,H,5]. Returns tokens-decoded [P,S,H,6]."""
        P, L, _ = x.shape
        assert L + pred_len <= self.max_context
        x = torch.clip(torch.as_tensor(x), -self.clip, self.clip)
        xs, ys = torch.as_tensor(x_stamp), torch.as_tensor(y_stamp)
        s1, s2 = self.tok.encode(x, half=True)
        rep = lambda t: t.repeat_interleave(S, 0)
        caches = [dict(cap=L + pred_len) for _ in self.m.transformer]
        dc = dict(cap=L + pred_len)
        H = self._forward(s1, s2, xs, caches, 0)              # [P,L,d], prefill once per point
        self._dep_kv(H, 0, dc)
        for c in caches + [dc]:
            _expand(c, S)
        h_last = rep(H[:, -1])
        g1, g2 = [], []
        for i in range(pred_len):
            n1 = _sample(self.m.head(h_last), T, top_k, top_p)
            n2 = _sample(self._s2_logits(h_last, n1, dc), T, top_k, top_p)
            g1.append(n1); g2.append(n2)
            if i < pred_len - 1:
                h = self._forward(n1[:, None], n2[:, None], rep(ys[:, i:i + 1]), caches, L + i)
                self._dep_kv(h, L + i, dc)
                h_last = h[:, -1]
        # tokenizer decoder (causal): context once per point, then the generated tokens per sample
        tk = self.tok
        dcache = [dict(cap=L + pred_len) for _ in tk.decoder]
        def dec(a, b, start, cs):
            z = tk.post_quant_embed(tk.indices_to_bits([a, b], half=True))
            pos = torch.arange(start, start + a.shape[1])
            for blk, c in zip(tk.decoder, cs):
                z = self._block(blk, z, c, pos)
            return tk.head(z)
        dec(s1, s2, 0, dcache)
        for c in dcache:
            _expand(c, S)
        z = dec(torch.stack(g1, 1), torch.stack(g2, 1), L, dcache)
        return z.reshape(P, S, pred_len, -1).numpy()


def prepare(df_window, ts_window, ts_future, clip=5.0):
    """Normalise a context window exactly like KronosPredictor.predict (stats from the context only)."""
    x = df_window[["open", "high", "low", "close", "volume", "amount"]].values.astype(np.float32)
    mu, sd = x.mean(0), x.std(0)
    xn = np.clip((x - mu) / (sd + 1e-5), -clip, clip)
    xs = calc_time_stamps(pd.Series(ts_window)).values.astype(np.float32)
    ys = calc_time_stamps(pd.Series(ts_future)).values.astype(np.float32)
    return xn, xs, ys, mu, sd
