// VPDRAW.GLSL - Silicon Coast, sprites HD sans DLL (format SC-HD v2), licence MIT.
// Derive du shader de sommets d'origine : pour tout ce qui n'est pas un cadre SC-HD,
// les sorties (vTc, vRef, vColor, gl_Position) sont exactement celles d'origine.
// Pour un cadre SC-HD v2 (repere par ses colonnes-reperes aux coins du quad), le quad est
// ramene sur le bloc-sonde (taille et place du sprite d'origine) et la disposition du
// cadre est transmise au shader de fragments.
// Pour un cadre en disposition F (familles dessinees par FXBltFrom : dragons, wyvernes...),
// le quad n'est pas deplace : le shader de sommets transmet seulement la "phase" du cadre
// (origine modulo 128 et 8, commune aux cadres F voisins dans l'atlas) et le shader de
// fragments decode le cadre lui-meme.
uniform vec4 uST;
uniform mediump vec2 uTcScale;
uniform lowp sampler2D uTex;

attribute vec2 aPos;
attribute highp vec2 aTc;
attribute lowp vec4 aColor;
attribute highp vec2 aRef;

varying highp vec2 vTc;
varying highp vec2 vRef;
varying lowp vec4 vColor;

varying highp vec4 vHdA;     // origine du bloc-sonde (texels d'atlas), w, h
varying highp vec4 vHdB;     // origine de l'image HD (texels d'atlas), k, drapeau HD (1)
varying highp vec4 vHdC;     // alpha de reference, ombre presente, palette a alpha, marge
varying highp vec4 vHdS;     // couleur de reference de l'ombre
varying lowp vec4 vColorHD;  // couleur de sommet d'origine (vColor vaut 0 pour un cadre HD)
varying highp vec4 vHdF;     // disposition F : phase du cadre (cercles unite x 128 et y 8), 0 si absent

const float SPINE = 60.0;
const float GAP = 4.0;
const float PAT_A = 1485.0;  // 1,0,1,1,0,0,1,1,1,0,1,0 (bit de poids faible d'abord)
const float PAT_B = 2259.0;  // 1,1,0,0,1,0,1,1,0,0,0,1

float texA(vec2 t)
{
	return texture2D(uTex, (t + 0.5) * uTcScale).a;
}

float bitAt(float x0, float dir, float y, float j)
{
	return texA(vec2(x0 + dir * j, y)) > 0.002 ? 1.0 : 0.0;
}

bool patternOK(float x0, float dir, float y, float pat)
{
	float p = pat;
	for (int j = 0; j < 12; j++)
	{
		float want = mod(p, 2.0);
		p = floor(p * 0.5);
		if (bitAt(x0, dir, y, float(j)) != want)
			return false;
	}
	return true;
}

float field(float x0, float dir, float y, float j0, float n)
{
	float v = 0.0;
	float p = 1.0;
	for (int i = 0; i < 10; i++)
	{
		if (float(i) >= n)
			break;
		v += p * bitAt(x0, dir, y, j0 + float(i));
		p *= 2.0;
	}
	return v;
}

// lit une ligne de spine ; renvoie faux si le motif ou la somme de controle ne vont pas
bool decodeRow(float x0, float dir, float y, out vec4 f0, out vec2 f1)
{
	f0 = vec4(0.0);
	f1 = vec2(0.0);
	if (!patternOK(x0, dir, y, dir > 0.0 ? PAT_A : PAT_B))
		return false;
	float r = field(x0, dir, y, 12.0, 10.0);
	float lay = bitAt(x0, dir, y, 22.0);
	float k = field(x0, dir, y, 23.0, 3.0) + 1.0;
	float w = field(x0, dir, y, 26.0, 10.0);
	float h = field(x0, dir, y, 36.0, 10.0);
	float fl = field(x0, dir, y, 46.0, 4.0);
	float cs = field(x0, dir, y, 50.0, 8.0);
	float c = mod(r + lay * 37.0 + (k - 1.0) * 53.0 + w * 7.0 + h * 11.0 + fl * 97.0 + 89.0, 256.0);
	if (abs(cs - c) > 0.5 || w < 0.5 || h < 0.5)
		return false;
	f0 = vec4(r, lay, k, fl);
	f1 = vec2(w, h);
	return true;
}

// grille des plans de l'image HD (drapeau 2 : 5 plans de sous-teintes sur ((drapeaux / 4) mod 4) + 1 colonnes)
vec2 planesGrid(float fl)
{
	if (mod(floor(fl / 2.0), 2.0) < 0.5)
		return vec2(1.0);
	float cols = mod(floor(fl / 4.0), 4.0) + 1.0;
	return vec2(cols, ceil(5.0 / cols));
}

// dimensions du cadre (WH), bloc-sonde et image HD (coordonnees locales du cadre)
void layoutDims(float lay, float k, float fl, vec2 wh, out vec2 WH, out vec2 probe, out vec2 hd)
{
	vec2 g = planesGrid(fl);
	if (lay < 0.5)
	{
		WH = vec2(2.0 * SPINE + wh.x + GAP + g.x * k * wh.x, g.y * k * wh.y);
		probe = vec2(SPINE, WH.y - wh.y);
		hd = vec2(SPINE + wh.x + GAP, 0.0);
	}
	else
	{
		WH = vec2(2.0 * SPINE + g.x * k * wh.x, g.y * k * wh.y + GAP + wh.y);
		probe = vec2(SPINE, g.y * k * wh.y + GAP);
		hd = vec2(SPINE, 0.0);
	}
}

// ---------------------------------------------------------------- disposition F
const float F_BW = 128.0;
const float F_SB = 16.0;
const float F_PER = 8.0;

bool fSync(float x0, float y)
{
	return bitAt(x0, 1.0, y, 0.0) < 0.5 && bitAt(x0, 1.0, y, 1.0) > 0.5
	    && bitAt(x0, 1.0, y, 2.0) > 0.5 && bitAt(x0, 1.0, y, 3.0) < 0.5;
}

float fData(float x0, float y, float d)
{
	float s = floor(d / 9.0);
	return bitAt(x0 + F_SB * s + 7.0, 1.0, y, d - 9.0 * s);
}

float fField(float x0, float y, float d0, float n)
{
	float v = 0.0;
	float p = 1.0;
	for (int i = 0; i < 12; i++)
	{
		if (float(i) >= n)
			break;
		v += p * fData(x0, y, d0 + float(i));
		p *= 2.0;
	}
	return v;
}

// bloc complet en (x0, y) : origine du cadre et parametres (w, h, k, drapeaux), sous-disposition
bool fBlock(float x0, float y, out vec2 org, out vec4 P, out float sub)
{
	org = vec2(0.0);
	P = vec4(0.0);
	sub = 0.0;
	for (int s = 0; s < 8; s++)
	{
		float xs = x0 + F_SB * float(s);
		if (!fSync(xs, y))
			return false;
		if (abs(field(xs, 1.0, y, 4.0, 3.0) - float(s)) > 0.5)
			return false;
	}
	float b = fField(x0, y, 0.0, 3.0);
	float m = fField(x0, y, 3.0, 7.0);
	float k = fField(x0, y, 10.0, 3.0) + 1.0;
	float w = fField(x0, y, 13.0, 10.0);
	float h = fField(x0, y, 23.0, 10.0);
	float fl = fField(x0, y, 33.0, 4.0);
	sub = fField(x0, y, 37.0, 1.0);
	float cs = fField(x0, y, 38.0, 12.0);
	float c = mod(b * 7.0 + m * 13.0 + (k - 1.0) * 53.0 + w * 31.0 + h * 37.0 + fl * 97.0 + sub * 131.0 + 1543.0, 4096.0);
	if (abs(cs - c) > 0.5 || w < 0.5 || h < 0.5)
		return false;
	org = vec2(x0 - b * F_BW, y - m * F_PER);
	P = vec4(w, h, k, fl);
	return true;
}

float fRowsNeeded(float n)
{
	return n - 1.0 + floor((n - 1.0) / 7.0) + 2.0;
}

// dimensions (W, H) du cadre F ; bloc-sonde ; P = (w, h, k, drapeaux)
vec2 fDims(vec4 P, float sub, out vec2 probe)
{
	float M = 4.0;
	float W;
	float H;
	vec2 g = planesGrid(P.w);
	if (sub < 0.5)
	{
		probe = vec2(M, fRowsNeeded(g.y * P.z * P.y) + M);
		W = max(g.x * P.z * P.x, P.x + 2.0 * M);
		H = probe.y + P.y + M;
	}
	else
	{
		probe = vec2(M, M);
		W = P.x + 2.0 * M + g.x * P.z * P.x;
		H = max(fRowsNeeded(g.y * P.z * P.y), probe.y + P.y + M);
	}
	return vec2(ceil(W / F_BW) * F_BW, ceil(H / F_PER) * F_PER);
}

bool fTry(vec2 tc, float x0, float y, out vec2 org, out vec4 P, out float sub)
{
	org = vec2(0.0);
	P = vec4(0.0);
	sub = 0.0;
	// jamais hors de l'atlas (la texture est bornee au bord : une ligne hors de l'atlas relirait la ligne 0)
	if (x0 < 0.0 || y < 0.0 || x0 + F_BW > 1.0 / uTcScale.x + 0.5 || y > 1.0 / uTcScale.y - 0.5)
		return false;
	if (!fSync(x0, y))
		return false;
	if (!fBlock(x0, y, org, P, sub))
		return false;
	vec2 pr;
	vec2 WH = fDims(P, sub, pr);
	return tc.x >= org.x - 0.01 && tc.y >= org.y - 0.01 && tc.x <= org.x + WH.x + 0.01 && tc.y <= org.y + WH.y + 0.01;
}

// cherche un cadre F qui contient le sommet ; les sommets d'un meme quad trouvent des cadres de meme phase
bool fFind(vec2 tc, vec2 ref, out vec2 org, out vec4 P, out float sub)
{
	// 1. sommet haut-gauche (ou decoupe a gauche et en haut) : origine exacte tc - aRef
	if (fTry(tc, tc.x - ref.x, tc.y - ref.y, org, P, sub))
		return true;
	// 2. bords non decoupes : bord gauche (bloc 0) ou droit (dernier bloc), lignes speciales tous les 8
	//    depuis le bord haut ou le bord bas (balayage long : murs "effacants" sur un coin)
	for (int j = 0; j < 32; j++)
	{
		float dy = 8.0 * float(j);
		if (fTry(tc, tc.x, tc.y + dy, org, P, sub))
			return true;
		if (fTry(tc, tc.x - F_BW, tc.y + dy, org, P, sub))
			return true;
		if (fTry(tc, tc.x, tc.y - 8.0 - dy, org, P, sub))
			return true;
		if (fTry(tc, tc.x - F_BW, tc.y - 8.0 - dy, org, P, sub))
			return true;
	}
	// 3. sommet decoupe par la fenetre : 16 lignes autour, colonne exacte des sommets de gauche,
	//    sous-bloc commencant dans les 16 colonnes a gauche
	for (int j = 0; j < 16; j++)
	{
		float y = j < 8 ? tc.y - 1.0 - float(j) : tc.y + float(j - 8);
		if (fTry(tc, tc.x - ref.x, y, org, P, sub))
			return true;
		for (int i = 0; i <= 16; i++)
		{
			float xs = tc.x - float(i);
			if (xs < 0.0)
				break;
			if (!fSync(xs, y))
				continue;
			float s = field(xs, 1.0, y, 4.0, 3.0);
			if (fTry(tc, xs - F_SB * s, y, org, P, sub))
				return true;
		}
	}
	return false;
}

void main()
{
	vec2 pos = aPos;
	vec2 tc = aTc;
	vColor = aColor;
	vColorHD = aColor;
	vHdA = vec4(0.0);
	vHdB = vec4(0.0);
	vHdC = vec4(0.0);
	vHdS = vec4(0.0);
	vHdF = vec4(0.0);
	bool hd = false;

	// Les blits de creatures (surface FX) ont aRef.y = 1 (ou 2 avec les contours de sprites).
	// Quad decoupe au rect interieur de la surface FX : (1,1,w-1,h-1) sans contours, (2,2,w-3,h-3) avec ;
	// en miroir tc.x = w - tc.x, donc avec contours les ecarts horizontaux au cadre s'echangent (1 et 2).
	float eLT = -1.0;
	float eRB = 0.0;
	float eLx = 0.0;
	float eRx = 0.0;
	bool mirroredQ = aRef.x > 2.5;
	if (abs(aRef.y - 1.0) < 0.25)
	{
		eLT = 0.0;
		eRB = 0.0;
	}
	else if (abs(aRef.y - 2.0) < 0.25)
	{
		eLT = 2.0;
		eRB = 1.0;
		eLx = mirroredQ ? 1.0 : 2.0;
		eRx = mirroredQ ? 2.0 : 1.0;
	}

	if (eLT >= 0.0)
	{
		bool found = false;
		vec2 origin = vec2(0.0);
		vec2 WH = vec2(0.0);
		vec2 probe = vec2(0.0);
		vec2 hdo = vec2(0.0);
		vec4 f0 = vec4(0.0);
		vec2 f1 = vec2(0.0);
		float sx = 0.0;
		float sy = 0.0;
		// 1re passe : ligne de spine confirmee par la spine opposee ; 2e passe (mur "effacant" sur la spine
		// opposee) : confirmee par une autre ligne de la meme spine
		for (int pass = 0; pass < 2; pass++)
		{
			if (found)
				break;
			for (int hyp = 0; hyp < 4; hyp++)
			{
				float hx = mod(float(hyp), 2.0);          // 0 : bord gauche du cadre, 1 : bord droit
				float hy = floor(float(hyp) * 0.5);       // 0 : haut, 1 : bas
				float xs = hx < 0.5 ? aTc.x + eLx : aTc.x - 1.0 - eRx;
				float dir = hx < 0.5 ? 1.0 : -1.0;
				float y0 = hy < 0.5 ? aTc.y + eLT : aTc.y - 1.0 - eRB;
				float sgn = hy < 0.5 ? 1.0 : -1.0;
				// lignes 0..7 une a une, puis de 8 en 8 jusqu'a 1024 (murs "effacants" sur un coin)
				for (int j = 0; j < 136; j++)
				{
					float dj = float(j) < 8.0 ? float(j) : 8.0 + (float(j) - 8.0) * 8.0;
					float yy = y0 + sgn * dj;
					vec4 g0;
					vec2 g1;
					if (!decodeRow(xs, dir, yy, g0, g1))
						continue;
					vec2 gWH;
					vec2 gpr;
					vec2 ghd;
					layoutDims(g0.y, g0.z, g0.w, g1, gWH, gpr, ghd);
					float rExp = hy < 0.5 ? dj : gWH.y - 1.0 - dj;
					if (abs(g0.x - rExp) > 0.5 || gWH.x > 1023.5 || gWH.y > 1023.5)
						break;                            // ligne valide mais pas a la bonne place
					vec2 o = vec2(hx < 0.5 ? xs : xs - gWH.x + 1.0, yy - g0.x);
					bool ok = false;
					if (pass == 0)
					{
						// controle croise : la spine opposee doit etre sur la meme ligne
						ok = hx < 0.5 ? patternOK(o.x + gWH.x - 1.0, -1.0, yy, PAT_B)
						              : patternOK(o.x, 1.0, yy, PAT_A);
					}
					else
					{
						// une des 3 lignes suivantes de la meme spine (multiples de 8 depuis le bord) concorde
						for (int q = 1; q <= 3; q++)
						{
							float e2 = 8.0 * (floor(dj / 8.0) + float(q));
							if (e2 > gWH.y - 1.0)
								break;
							vec4 h0;
							vec2 h1;
							if (!decodeRow(xs, dir, y0 + sgn * e2, h0, h1))
								continue;
							float r2 = hy < 0.5 ? e2 : gWH.y - 1.0 - e2;
							vec3 dd = abs(h0.yzw - g0.yzw);
							vec2 de = abs(h1 - g1);
							if (abs(h0.x - r2) < 0.5 && max(dd.x, max(dd.y, dd.z)) < 0.5 && max(de.x, de.y) < 0.5)
							{
								ok = true;
								break;
							}
						}
					}
					if (!ok)
						continue;
					found = true;
					origin = o;
					WH = gWH;
					probe = gpr;
					hdo = ghd;
					f0 = g0;
					f1 = g1;
					sx = hx;
					sy = hy;
					break;
				}
				if (found)
					break;
			}
		}

		if (found)
		{
			// alpha de reference (alpha d'un texel opaque sans mur) et couleur de l'ombre :
			// memes texels lus par les 4 sommets -> valeurs identiques sur tout le quad
			float a0 = 0.0;
			for (int i = 0; i <= 16; i++)
			{
				// 1er texel de chaque spine (toujours a 1) sur 17 lignes reparties
				float ry = floor(float(i) * 0.0625 * (WH.y - 1.0));
				a0 = max(a0, texA(vec2(origin.x, origin.y + ry)));
				a0 = max(a0, texA(vec2(origin.x + WH.x - 1.0, origin.y + ry)));
			}
			for (int i = 0; i < 4; i++)
			{
				for (int j = 0; j < 4; j++)
				{
					vec2 q = probe + floor((vec2(float(i), float(j)) + 0.5) * 0.25 * f1);
					a0 = max(a0, texA(origin + q));
				}
			}
			// texel de reference d'ombre (indice 1) : premier non efface parmi 2 x 9 lignes
			vec4 shadow = vec4(0.0);
			for (int i = 8; i >= 0; i--)
			{
				float ry = floor(float(i) * 0.125 * (WH.y - 1.0));
				vec4 s1 = texture2D(uTex, (origin + vec2(58.0, ry) + 0.5) * uTcScale);
				vec4 s2 = texture2D(uTex, (origin + vec2(WH.x - 59.0, ry) + 0.5) * uTcScale);
				if (s2.a > 0.002) shadow = vec4(s2.rgb, 1.0);
				if (s1.a > 0.002) shadow = vec4(s1.rgb, 1.0);
			}

			// ramener le sommet sur le coin correspondant du bloc-sonde
			float m = eLT > 0.5 ? 2.0 : 0.0;          // avec contours : 2 texels autour pour le halo
			vec2 cur = aTc - origin;
			vec2 target = vec2(sx < 0.5 ? probe.x - m : probe.x + f1.x + m,
			                   sy < 0.5 ? probe.y - m : probe.y + f1.y + m);
			vec2 dlt = target - cur;
			tc = aTc + dlt;
			pos = aPos + vec2(mirroredQ ? -dlt.x : dlt.x, dlt.y);

			hd = true;
			vColor = vec4(0.0);
			vHdA = vec4(origin + probe, f1);
			vHdB = vec4(origin + hdo, f0.z, 1.0);
			vHdC = vec4(max(a0, 0.004), shadow.a, f0.w, m);
			vHdS = vec4(shadow.rgb, 0.0);
		}
	}

	if (!hd)
	{
		vec2 fo;
		vec4 fp;
		float fsub;
		if (fFind(aTc, aRef, fo, fp, fsub))
		{
			vec2 fpr;
			vec2 fWH = fDims(fp, fsub, fpr);
			// alpha de reference : bits a 1 des blocs (colonne 1) sur 8 lignes speciales + 16 texels du bloc-sonde
			float a0 = 0.0;
			vec4 shadow = vec4(0.0);
			float nrow = fWH.y / F_PER - 1.0;
			for (int i = 0; i < 8; i++)
			{
				float ry = fo.y + F_PER * floor(float(i) * nrow / 7.0);
				a0 = max(a0, texA(vec2(fo.x + 1.0, ry)));
				a0 = max(a0, texA(vec2(fo.x + fWH.x - F_BW + 1.0, ry)));
				vec4 s1 = texture2D(uTex, (vec2(fo.x + F_BW - 1.0, ry) + 0.5) * uTcScale);
				vec4 s2 = texture2D(uTex, (vec2(fo.x + fWH.x - 1.0, ry) + 0.5) * uTcScale);
				if (shadow.a < 0.5 && s1.a > 0.002) shadow = vec4(s1.rgb, 1.0);
				if (shadow.a < 0.5 && s2.a > 0.002) shadow = vec4(s2.rgb, 1.0);
			}
			for (int i = 0; i < 4; i++)
			{
				for (int j = 0; j < 4; j++)
				{
					vec2 q = fpr + floor((vec2(float(i), float(j)) + 0.5) * 0.25 * fp.xy);
					a0 = max(a0, texA(fo + q));
				}
			}
			float tx = 6.2831853 * mod(fo.x, F_BW) / F_BW;
			float ty = 6.2831853 * mod(fo.y, F_PER) / F_PER;
			vHdF = vec4(cos(tx), sin(tx), cos(ty), sin(ty));
			// indices (normalises par la longueur de vHdF.xy dans le shader de fragments)
			vHdA = vec4(fp.x, fp.y, fp.z * 32.0 + fp.w * 2.0 + fsub, 0.0);
			vHdB = vec4(fo, 0.0, 0.0);              // origine du cadre (repli si les blocs sont effaces)
			vHdC = vec4(max(a0, 0.004), shadow.a, 0.0, 0.0);
			vHdS = vec4(shadow.rgb, 0.0);
			vColorHD = aColor;
		}
	}

	vTc = tc * uTcScale;
	vRef = aRef * uTcScale;

	gl_Position.xy = pos * uST.xy + uST.zw;
	gl_Position.zw = vec2( 1, 1 );
	gl_PointSize = 1.0;
}
