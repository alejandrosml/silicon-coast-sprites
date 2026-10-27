// --- Silicon Coast : rendu d'un cadre SC-HD (bloc commun aux shaders de fragments) ---
// Cadre v2 (sommets deplaces sur le bloc-sonde par VPDRAW) :
//   vHdA : origine du bloc-sonde (texels d'atlas), w, h
//   vHdB : origine de l'image HD (texels d'atlas), k, drapeau HD (1)
//   vHdC : alpha de reference a0, ombre presente, palette a alpha, marge de halo
//   vHdS : couleur de reference de l'ombre
// Cadre en disposition F (familles FXBltFrom, sommets non deplaces) :
//   vHdF : phase du cadre sur deux cercles unite (origine modulo 128 en x, modulo 8 en y) ;
//          sa longueur g vaut 1 si les trois sommets ont trouve le cadre, moins sinon
//   vHdA : indices w, h, k*32 + drapeaux*2 + sous-disposition (multiplies par g)
//   vHdC : a0, ombre presente (multiplies par g) ;  vHdS : couleur de l'ombre (multipliee par g)
//   Chaque fragment decode lui-meme son cadre a partir de la phase.
varying highp vec4 vHdA;
varying highp vec4 vHdB;
varying highp vec4 vHdC;
varying highp vec4 vHdS;
varying highp vec4 vHdF;
varying lowp vec4 vColorHD;

// etat du cadre pour ce fragment (rempli par scSetup)
vec2 scPO;      // origine du bloc-sonde (texels d'atlas)
vec2 scPS;      // w, h
vec2 scHO;      // origine de l'image HD
float scK;
float scA0;
float scShOn;
float scPal;
vec3 scSh;
float scFl;     // drapeaux du cadre (1 : palette a alpha, 2 : sous-teintes, 4-8 : colonnes des plans - 1)
vec2 scGrid;    // grille des plans (colonnes, lignes)
float scF;      // 1 : disposition F (lignes speciales a sauter)
float scRow0;   // disposition F : premiere ligne du cadre
float scMargin; // halo autorise autour du bloc-sonde (texels du monde)
vec2 scFw;      // empreinte du fragment en texels (fwidth), calculee en debut de main (flot uniforme)

vec4 scTex(vec2 t)
{
	return texture2D(uTex, (t + 0.5) * uTcScale);
}

// texel HD (i, j) -> texel d'atlas
vec2 scHdAt(vec2 t)
{
	if (scF > 0.5)
		return vec2(scHO.x + t.x, scHO.y + t.y + floor(t.y / 7.0) + 1.0);
	return scHO + t;
}

vec2 scGridOf(float fl)
{
	if (mod(floor(fl / 2.0), 2.0) < 0.5)
		return vec2(1.0);
	float cols = mod(floor(fl / 4.0), 4.0) + 1.0;
	return vec2(cols, ceil(5.0 / cols));
}

// texel du plan p (0 : I, 1 : S, 2-4 : bits de F) a la position HD t
vec4 scPlane(vec2 t, float p)
{
	vec2 cell = vec2(mod(p, scGrid.x), floor(p / scGrid.x));
	return scTex(scHdAt(t + cell * scPS * scK));
}

// sous-teinte (bg2hd, Q3M) : couleur = (P[I] (8 - F) + P[S] F + 4) >> 3 ; chaque bit de F est un texel
// d'indice I (0) ou S (1), compare aux couleurs des plans I et S (remplacements de palette et teintes compris)
vec3 scSubShade(vec4 cI, vec2 t)
{
	vec4 cS = scPlane(t, 1.0);
	vec3 dIS = abs(cS.rgb - cI.rgb);
	if (cS.a < 0.002 || max(dIS.r, max(dIS.g, dIS.b)) < 0.001)
		return cI.rgb;
	float F = 0.0;
	for (int b = 0; b < 3; b++)
	{
		vec4 cb = scPlane(t, 2.0 + float(b));
		vec3 d1 = cb.rgb - cS.rgb;
		vec3 d0 = cb.rgb - cI.rgb;
		if (dot(d1, d1) < dot(d0, d0))
			F += b == 0 ? 1.0 : (b == 1 ? 2.0 : 4.0);
	}
	return floor((floor(cI.rgb * 255.0 + 0.5) * (8.0 - F) + floor(cS.rgb * 255.0 + 0.5) * F + 4.0) / 8.0) / 255.0;
}

// texel HD classe : renvoie (rgb * rel, rel), rel = 1 (opaque), 0.5 (ombre) ou 0 (vide)
vec4 scHdTexel(vec2 t)
{
	vec4 c = scTex(scHdAt(t));
	if (c.a < 0.002)
		return vec4(0.0);
	if (scGrid.x * scGrid.y > 1.5)
		c.rgb = scSubShade(c, t);
	// Un texel opaque vaut a0 ; une ombre a0/2 ; un mur "attenuant" tombe sur la zone HD
	// (et non sur le sprite) divise l'alpha par 2 sans toucher la couleur : un texel a alpha
	// reduit qui n'a pas la couleur de l'ombre est donc un texel opaque sous un mur.
	float rel = 1.0;
	bool lowA = c.a < 0.75 * scA0;
	bool palAlpha = scPal > 0.5;
	if (lowA)
	{
		if (scShOn > 0.5)
		{
			vec3 dc = abs(c.rgb - scSh);
			if (max(dc.r, max(dc.g, dc.b)) < 0.003)
				rel = 0.5;
			else if (palAlpha)
				rel = c.a / scA0;
		}
		else
		{
			rel = palAlpha ? c.a / scA0 : 0.5;
		}
	}
	return vec4(c.rgb * rel, rel);
}

// bilineaire premultiplie dans l'image HD (bornee a l'image)
vec4 scHdBilinear(vec2 u, vec2 size)
{
	vec2 q = u - 0.5;
	vec2 i0 = floor(q);
	vec2 f = q - i0;
	vec2 a = clamp(i0, vec2(0.0), size - 1.0);
	vec2 b = clamp(i0 + 1.0, vec2(0.0), size - 1.0);
	vec4 t00 = scHdTexel(vec2(a.x, a.y));
	vec4 t10 = scHdTexel(vec2(b.x, a.y));
	vec4 t01 = scHdTexel(vec2(a.x, b.y));
	vec4 t11 = scHdTexel(vec2(b.x, b.y));
	return mix(mix(t00, t10, f.x), mix(t01, t11, f.x), f.y);
}

float scProbeA(vec2 t)
{
	if (scF > 0.5)
	{
		// ligne speciale (bits de reperage) : effet des murs pris sur les lignes voisines du bloc-sonde
		float ay = scPO.y + t.y;
		if (mod(ay - scRow0, 8.0) < 0.5)
		{
			float up = t.y - 1.0;
			float dn = t.y + 1.0;
			if (up < 0.0)
				return scTex(vec2(scPO.x + t.x, scPO.y + dn)).a;
			if (dn > scPS.y - 1.0)
				return scTex(vec2(scPO.x + t.x, scPO.y + up)).a;
			return 0.5 * (scTex(vec2(scPO.x + t.x, scPO.y + up)).a + scTex(vec2(scPO.x + t.x, scPO.y + dn)).a);
		}
	}
	return scTex(scPO + t).a;
}

// effet des murs (et transparence) lu dans le bloc-sonde, bilineaire borne au bloc
float scProbeBilinear(vec2 d)
{
	vec2 q = d - 0.5;
	vec2 i0 = floor(q);
	vec2 f = q - i0;
	vec2 a = clamp(i0, vec2(0.0), scPS - 1.0);
	vec2 b = clamp(i0 + 1.0, vec2(0.0), scPS - 1.0);
	float v00 = scProbeA(vec2(a.x, a.y));
	float v10 = scProbeA(vec2(b.x, a.y));
	float v01 = scProbeA(vec2(a.x, b.y));
	float v11 = scProbeA(vec2(b.x, b.y));
	return mix(mix(v00, v10, f.x), mix(v01, v11, f.x), f.y);
}

// couleur HD (non premultipliee) au point d du bloc-sonde (unites du monde)
vec4 scHdSample(vec2 d, vec2 fw)
{
	float k = scK;
	vec2 size = scPS * k;
	vec2 u = d * k;
	float f = max(fw.x, fw.y) * k;
	vec4 acc;
	if (f <= 1.25)
	{
		acc = scHdBilinear(u, size);
	}
	else
	{
		float n = f < 2.5 ? 2.0 : 3.0;
		acc = vec4(0.0);
		for (int i = 0; i < 3; i++)
		{
			for (int j = 0; j < 3; j++)
			{
				if (float(i) < n && float(j) < n)
				{
					vec2 off = (vec2(float(i), float(j)) + 0.5) / n - 0.5;
					acc += scHdBilinear(u + off * fw * k, size);
				}
			}
		}
		acc /= n * n;
	}
	vec3 rgb = acc.a > 0.0001 ? acc.rgb / acc.a : vec3(0.0);
	return vec4(rgb, acc.a);
}

// couleur finale d'un fragment HD (avant couleur de sommet et teinte)
vec4 scHdColor()
{
	vec2 p = vTc / uTcScale;
	vec2 d = p - scPO;
	vec2 fw = scFw;
	vec2 dc = clamp(d, vec2(0.0), scPS - 0.0001);
	vec4 c = scHdSample(dc, fw);
	float wa = scProbeBilinear(dc);
	if (d.x < 0.0 || d.y < 0.0 || d.x >= scPS.x || d.y >= scPS.y)
		c.a = 0.0;
	return vec4(c.rgb, c.a * wa);
}

// ---------------------------------------------------------------- decodage F par fragment
float scBit(vec2 t)
{
	return scTex(t).a > 0.002 ? 1.0 : 0.0;
}

bool scFSync(vec2 t)
{
	return scBit(t) < 0.5 && scBit(t + vec2(1.0, 0.0)) > 0.5 && scBit(t + vec2(2.0, 0.0)) > 0.5
	    && scBit(t + vec2(3.0, 0.0)) < 0.5;
}

// debut de bloc verifie : synchro et indice des deux premiers sous-blocs (14 lectures)
bool scFHead(vec2 b)
{
	if (!scFSync(b) || !scFSync(b + vec2(16.0, 0.0)))
		return false;
	float i0 = scBit(b + vec2(4.0, 0.0)) + 2.0 * scBit(b + vec2(5.0, 0.0)) + 4.0 * scBit(b + vec2(6.0, 0.0));
	float i1 = scBit(b + vec2(20.0, 0.0)) + 2.0 * scBit(b + vec2(21.0, 0.0)) + 4.0 * scBit(b + vec2(22.0, 0.0));
	return i0 < 0.5 && abs(i1 - 1.0) < 0.5;
}

float scFData(vec2 b0, float d)
{
	float s = floor(d / 9.0);
	return scBit(vec2(b0.x + 16.0 * s + 7.0 + (d - 9.0 * s), b0.y));
}

float scFField(vec2 b0, float d0, float n)
{
	float v = 0.0;
	float p = 1.0;
	for (int i = 0; i < 12; i++)
	{
		if (float(i) >= n)
			break;
		v += p * scFData(b0, d0 + float(i));
		p *= 2.0;
	}
	return v;
}

float scFCheck(float b, float m, float k, float w, float h, float fl, float sub)
{
	return mod(b * 7.0 + m * 13.0 + (k - 1.0) * 53.0 + w * 31.0 + h * 37.0 + fl * 97.0 + sub * 131.0 + 1543.0, 4096.0);
}

float scFRowsNeeded(float n)
{
	return n - 1.0 + floor((n - 1.0) / 7.0) + 2.0;
}

// lit le bloc en b0 ; renvoie vrai et l'origine + parametres (w, h, k, drapeaux, sous-disposition)
bool scFBlock(vec2 b0, vec3 hint, out vec2 org, out vec4 P, out float sub)
{
	org = vec2(0.0);
	P = vec4(0.0);
	sub = 0.0;
	if (!scFSync(b0))
		return false;
	float b = scFField(b0, 0.0, 3.0);
	float m = scFField(b0, 3.0, 7.0);
	float cs = scFField(b0, 38.0, 12.0);
	// indices du shader de sommets (w, h, k, drapeaux, sous-disposition) : verifies par la somme de controle
	float hk = floor(hint.z / 32.0 + 0.001);
	float hf = floor((hint.z - hk * 32.0) / 2.0 + 0.001);
	float hs = hint.z - hk * 32.0 - hf * 2.0;
	if (abs(cs - scFCheck(b, m, hk, hint.x, hint.y, hf, hs)) < 0.5 && hint.x > 0.5)
	{
		P = vec4(hint.x, hint.y, hk, hf);
		sub = hs;
	}
	else
	{
		float k = scFField(b0, 10.0, 3.0) + 1.0;
		float w = scFField(b0, 13.0, 10.0);
		float h = scFField(b0, 23.0, 10.0);
		float fl = scFField(b0, 33.0, 4.0);
		sub = scFField(b0, 37.0, 1.0);
		if (abs(cs - scFCheck(b, m, k, w, h, fl, sub)) > 0.5 || w < 0.5 || h < 0.5)
			return false;
		P = vec4(w, h, k, fl);
	}
	org = vec2(b0.x - b * 128.0, b0.y - m * 8.0);
	return true;
}

// sonde et image HD du cadre F d'origine org
void scFLayout(vec2 org, vec4 P, float sub)
{
	float M = 4.0;
	vec2 gr = scGridOf(P.w);
	if (sub < 0.5)
	{
		scPO = org + vec2(M, scFRowsNeeded(gr.y * P.z * P.y) + M);
		scHO = org;
	}
	else
	{
		scPO = org + vec2(M, M);
		scHO = org + vec2(P.x + 2.0 * M, 0.0);
	}
	scPS = P.xy;
	scK = P.z;
	scFl = P.w;
	scPal = mod(P.w, 2.0);
	scGrid = scGridOf(P.w);
	scF = 1.0;
	scRow0 = org.y;
}

// Prepare le cadre du fragment. Renvoie 0 : rendu d'origine ; 1 : rendu HD ; -1 : a ecarter.
// halo : le fragment peut etre a moins de 'halo' texels du bloc-sonde (contours).
float scSetup(float halo)
{
	scF = 0.0;
	scRow0 = 0.0;
	scMargin = 0.0;
	scFl = 0.0;
	scGrid = vec2(1.0);
	float w2 = vHdB.w;
	if (w2 > 0.02)
	{
		// cadre v2. Chaque sommet qui a trouve le cadre transmet ses valeurs (identiques pour tout le quad) et le
		// poids 1 ; un sommet dont les reperes sont effaces (mur "effacant" sur toute une spine) transmet 0 et
		// reste a sa place : valeur = interpolee / poids interpole, puis bornes du bloc-sonde.
		float iw = 1.0 / w2;
		vec4 A = vHdA * iw;
		vec3 B = vHdB.xyz * iw;
		vec4 C = vHdC * iw;
		scPO = floor(A.xy + 0.5);
		scPS = floor(A.zw + 0.5);
		scHO = floor(B.xy + 0.5);
		scK = floor(B.z + 0.5);
		scA0 = C.x;
		scShOn = C.y > 0.5 ? 1.0 : 0.0;
		scFl = floor(C.z + 0.5);
		scPal = mod(scFl, 2.0);
		scGrid = scGridOf(scFl);
		scMargin = floor(C.w + 0.5);
		scSh = vHdS.rgb * iw;
		if (w2 < 0.999)
		{
			// sommets d'un meme cadre : valeurs entieres apres division ; sinon melange -> rien
			vec4 eA = abs(A - floor(A + 0.5));
			vec3 eB = abs(B - floor(B + 0.5));
			if (max(max(eA.x, eA.y), max(eA.z, eA.w)) > 0.02 || max(eB.x, max(eB.y, eB.z)) > 0.02)
				return -1.0;
			vec2 d = floor(vTc / uTcScale) + 0.5 - scPO;
			float mg = scMargin + 1.0;
			if (d.x < -mg || d.y < -mg || d.x > scPS.x + mg || d.y > scPS.y + mg)
				return -1.0;
		}
		return 1.0;
	}
	float g = length(vHdF.xy);
	if (g < 0.01)
		return 0.0;
	// ---- disposition F : phase -> bloc au-dessus a gauche du fragment
	float px = floor(mod(atan(vHdF.y, vHdF.x) / 6.2831853 * 128.0 + 128.5, 128.0));
	float py = floor(mod(atan(vHdF.w, vHdF.z) / 6.2831853 * 8.0 + 8.5, 8.0));
	vec2 T = floor(vTc / uTcScale);
	vec2 b0 = vec2(T.x - mod(T.x - px, 128.0), T.y - mod(T.y - py, 8.0));
	float fail = g > 0.999 ? -1.0 : 0.0;
	vec3 hint = vHdA.xyz / g;
	// 1. tri rapide (bloc du fragment lisible) : la cellule de 128 x 8 du fragment appartient a ce cadre
	//    (cadres alignes sur la phase) ; seuls les texels de la couleur du bloc-sonde (ou proches, pour le
	//    halo) continuent
	if (scFHead(b0))
	{
		vec4 mark = scTex(b0 + vec2(1.0, 0.0));
		bool cand = false;
		for (int i = 0; i < 5; i++)
		{
			if (cand)
				break;
			vec2 o = i == 0 ? vec2(0.0) : (i == 1 ? vec2(0.0, -1.0) : (i == 2 ? vec2(0.0, 1.0) : (i == 3 ? vec2(-halo, 0.0) : vec2(halo, 0.0))));
			if ((i == 1 || i == 2) && T.y != b0.y)
				continue;          // ligne ordinaire : le texel lui-meme suffit
			if ((i == 3 || i == 4) && halo < 0.5)
				continue;
			vec4 c = scTex(T + o);
			vec3 dc = abs(c.rgb - mark.rgb);
			if (c.a > 0.002 && max(dc.r, max(dc.g, dc.b)) < 0.004)
				cand = true;
		}
		if (halo > 0.5 && !cand)
		{
			for (int i = 0; i < 4; i++)
			{
				vec2 o = vec2(i < 2 ? -halo : halo, mod(float(i), 2.0) < 0.5 ? -halo : halo);
				vec4 c = scTex(T + o);
				vec3 dc = abs(c.rgb - mark.rgb);
				if (c.a > 0.002 && max(dc.r, max(dc.g, dc.b)) < 0.004)
					cand = true;
			}
		}
		if (!cand)
			return -1.0;
	}
	// 2. decodage : premier bloc lisible (le sien, sinon un voisin : un mur "effacant" peut en avoir efface)
	//    dont le cadre contient le fragment
	bool ok = false;
	vec2 org = vec2(0.0);
	vec4 P = vec4(0.0);
	float sub = 0.0;
	for (int i = 0; i < 13; i++)
	{
		if (ok)
			break;
		vec2 o = i == 0 ? vec2(0.0) : (i == 1 ? vec2(0.0, -8.0) : (i == 2 ? vec2(0.0, 8.0) : (i == 3 ? vec2(-128.0, 0.0) :
		         (i == 4 ? vec2(128.0, 0.0) : (i == 5 ? vec2(0.0, -16.0) : (i == 6 ? vec2(0.0, 16.0) : (i == 7 ? vec2(0.0, -24.0) :
		         (i == 8 ? vec2(0.0, 24.0) : (i == 9 ? vec2(0.0, -32.0) : (i == 10 ? vec2(0.0, 32.0) : (i == 11 ? vec2(-128.0, -8.0) : vec2(128.0, 8.0))))))))))));
		vec2 c = b0 + o;
		vec2 og;
		vec4 PP;
		float sb;
		if (c.x >= 0.0 && c.y >= 0.0 && scFBlock(c, hint, og, PP, sb))
		{
			vec2 gr2 = scGridOf(PP.w);
			vec2 WHf;
			if (sb < 0.5)
				WHf = vec2(max(gr2.x * PP.z * PP.x, PP.x + 8.0), scFRowsNeeded(gr2.y * PP.z * PP.y) + 8.0 + PP.y);
			else
				WHf = vec2(PP.x + 8.0 + gr2.x * PP.z * PP.x, max(scFRowsNeeded(gr2.y * PP.z * PP.y), PP.y + 8.0));
			WHf = vec2(ceil(WHf.x / 128.0) * 128.0, ceil(WHf.y / 8.0) * 8.0);
			if (T.x >= og.x && T.y >= og.y && T.x < og.x + WHf.x && T.y < og.y + WHf.y)
			{
				ok = true;
				org = og;
				P = PP;
				sub = sb;
			}
		}
	}
	if (!ok && g > 0.999)
	{
		// aucun bloc lisible pres du fragment (mur "effacant" etendu) : origine transmise par les sommets, si
		// elle est entiere et en phase (tous les sommets du quad ont trouve le meme cadre)
		vec2 oh = vHdB.xy / g;
		vec2 fr = abs(oh - floor(oh + 0.5));
		vec2 ph = vec2(mod(floor(oh.x + 0.5), 128.0), mod(floor(oh.y + 0.5), 8.0));
		float hk = floor(hint.z / 32.0 + 0.001);
		float hf = floor((hint.z - hk * 32.0) / 2.0 + 0.001);
		float hs = hint.z - hk * 32.0 - hf * 2.0;
		vec3 fh = abs(hint - floor(hint + 0.5));
		if (max(fr.x, fr.y) < 0.01 && abs(ph.x - px) < 0.5 && abs(ph.y - py) < 0.5 && max(fh.x, max(fh.y, fh.z)) < 0.01 && hint.x > 0.5)
		{
			org = floor(oh + 0.5);
			P = vec4(floor(hint.x + 0.5), floor(hint.y + 0.5), hk, hf);
			sub = hs;
			vec2 gr2 = scGridOf(P.w);
			vec2 WHf;
			if (sub < 0.5)
				WHf = vec2(max(gr2.x * P.z * P.x, P.x + 8.0), scFRowsNeeded(gr2.y * P.z * P.y) + 8.0 + P.y);
			else
				WHf = vec2(P.x + 8.0 + gr2.x * P.z * P.x, max(scFRowsNeeded(gr2.y * P.z * P.y), P.y + 8.0));
			WHf = vec2(ceil(WHf.x / 128.0) * 128.0, ceil(WHf.y / 8.0) * 8.0);
			ok = T.x >= org.x && T.y >= org.y && T.x < org.x + WHf.x && T.y < org.y + WHf.y;
		}
	}
	if (!ok)
		return fail;
	scFLayout(org, P, sub);
	vec2 d = T + 0.5 - scPO;
	if (d.x < -halo || d.y < -halo || d.x > scPS.x + halo || d.y > scPS.y + halo)
		return -1.0;
	scA0 = vHdC.x / g;
	scShOn = vHdC.y / g > 0.5 ? 1.0 : 0.0;
	scSh = vHdS.rgb / g;
	scMargin = halo;
	return 1.0;
}
// --- fin du bloc commun ---
