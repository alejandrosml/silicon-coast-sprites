# build_shaders.py - assemble les shaders de fragments Silicon Coast (le moteur ne gere pas #include)
import os, sys
D = os.path.dirname(os.path.abspath(__file__))
SH = D                                   # sources : ce dossier (shaders/src)
OUT = os.path.dirname(D)                 # shaders assembles : shaders/
os.makedirs(OUT, exist_ok=True)
common = open(os.path.join(SH, 'hd_common.glsl')).read()
LIC = "// Silicon Coast - sprites HD sans DLL (format SC-HD v2), licence MIT.\n" \
      "// Le chemin d'origine (cadres ordinaires) est celui du shader d'origine, inchange.\n"

FPDRAW = LIC + """uniform lowp	sampler2D	uTex;
uniform highp	vec4		uColorTone;
uniform mediump	vec2		uTcScale;
varying mediump	vec2		vTc;
varying lowp	vec4		vColor;

""" + common + """
void main()
{
	scFw = fwidth(vTc / uTcScale);    // derivees hors de tout branchement (voisins ecartes ou non)
	float hd = scSetup(0.0);
	if (hd < -0.5)
		discard;
	if (hd < 0.5)
	{
		vec4 texColor = texture2D( uTex, vTc ) * vColor;
		float grey = dot(texColor.rgb, vec3(0.299,0.587,0.114));
		vec3 tone = grey * uColorTone.rgb;
		gl_FragColor = vec4(mix(texColor.rgb, tone, uColorTone.a), texColor.a);
		return;
	}
	vec4 texColor = scHdColor() * vColorHD;
	float grey = dot(texColor.rgb, vec3(0.299,0.587,0.114));
	vec3 tone = grey * uColorTone.rgb;
	gl_FragColor = vec4(mix(texColor.rgb, tone, uColorTone.a), texColor.a);
}
"""

FPTONE = LIC + """uniform lowp sampler2D uTex;
uniform lowp vec4 uColorTone;
uniform mediump vec2 uTcScale;

varying mediump vec2 vTc;
varying lowp vec4 vColor;

""" + common + """
void main()
{
	scFw = fwidth(vTc / uTcScale);    // derivees hors de tout branchement (voisins ecartes ou non)
	float hd = scSetup(0.0);
	if (hd < -0.5)
		discard;
	if (hd < 0.5)
	{
		lowp vec4	c		= texture2D( uTex, vTc ) * vColor;
		lowp float	grey	= dot( c.rgb, vec3(0.299,0.587,0.114) );
		lowp vec3	tone	= grey * uColorTone.rgb;

		gl_FragColor = vec4( mix( c.rgb, tone, uColorTone.a ), c.a );
		return;
	}
	lowp vec4	c		= scHdColor() * vColorHD;
	lowp float	grey	= dot( c.rgb, vec3(0.299,0.587,0.114) );
	lowp vec3	tone	= grey * uColorTone.rgb;
	gl_FragColor = vec4( mix( c.rgb, tone, uColorTone.a ), c.a );
}
"""

FPSPRITE = LIC + """uniform lowp	sampler2D	uTex;
uniform lowp	float		uSpriteBlurAmount;
uniform mediump	vec2		uTcScale;
varying mediump	vec2		vTc;
varying lowp	vec4		vColor;

mediump float normpdf(in mediump float x, in mediump float sigma)
{
	return 0.39894*exp(-0.5*x*x/(sigma*sigma))/sigma;
}

""" + common + """
// halo des contours de sprites pour un cadre HD : texels HD au plus proche, decales comme
// l'original (0.0005 en coordonnees d'atlas 1024 = 0.512 texel du monde)
vec4 scHdRaw(vec2 d)
{
	if (d.x < 0.0 || d.y < 0.0 || d.x >= scPS.x || d.y >= scPS.y)
		return vec4(0.0);
	vec2 t = floor(d * scK);
	return scTex(scHdAt(t));
}

void main()
{
	scFw = fwidth(vTc / uTcScale);    // derivees hors de tout branchement (voisins ecartes ou non)
	float hd = scSetup(3.0);
	if (hd < -0.5)
		discard;
	if (hd < 0.5)
	{
		const int mSize = 5;
		const int kSize = (mSize-1)/2;
		int solidPixelCount = 0;
		mediump float kernel[mSize];
		lowp vec4 blur_colour = vec4(0.0);

		mediump float sigma = 7.0;
		mediump float Z = 0.0;
		for (int j = 0; j <= kSize; ++j)
		{
			kernel[kSize+j] = kernel[kSize-j] = normpdf(float(j), sigma);
		}
		for (int j = 0; j < mSize; ++j)
		{
			Z += kernel[j];
		}
		for (int i=-kSize; i <= kSize; ++i)
		{
			for (int j=-kSize; j <= kSize; ++j)
			{
				lowp vec4 sample = texture2D(uTex, (vTc+vec2(float(i) * .0005,float(j) * .0005)));
				blur_colour += kernel[kSize+j]*kernel[kSize+i]*sample;
				if (sample.a > 0.5)
				{
					solidPixelCount = solidPixelCount+1;
				}
			}
		}
		if (solidPixelCount > 0)
		{
			blur_colour.a = blur_colour.a * uSpriteBlurAmount;
		}
		blur_colour = blur_colour/(Z*Z);
		vec4 tex_color = texture2D(uTex, vTc);
		gl_FragColor = mix(blur_colour, tex_color, tex_color.a);
		return;
	}
	vec2 d = vTc / uTcScale - scPO;
	float wa = scProbeBilinear(clamp(d, vec2(0.0), scPS - 0.0001));
	float Z = 0.0;
	vec4 blur = vec4(0.0);
	int solid = 0;
	for (int i = -2; i <= 2; ++i)
	{
		for (int j = -2; j <= 2; ++j)
		{
			float kw = normpdf(float(i), 7.0) * normpdf(float(j), 7.0);
			vec4 s = scHdRaw(d + vec2(float(i), float(j)) * 0.512);
			s.a *= wa / max(scA0, 0.004);
			blur += kw * s;
			Z += kw;
			if (s.a > 0.5)
				solid = solid + 1;
		}
	}
	if (solid > 0)
		blur.a = blur.a * uSpriteBlurAmount;
	blur = blur / Z;
	vec4 tex = scHdColor();
	gl_FragColor = mix(blur, tex, tex.a);
}
"""

FPSELECT = LIC + """uniform lowp	sampler2D	uTex;
uniform lowp	float		uSpriteBlurAmount;
uniform mediump vec2		uTcScale;
varying mediump	vec2		vTc;
varying lowp	vec4		vColor;

mediump float normpdf(in mediump float x, in mediump float sigma)
{
	return 0.39894*exp(-0.5*x*x/(sigma*sigma))/sigma;
}

const float fSolidThreshold = 0.1;

""" + common + """
void main()
{
	scFw = fwidth(vTc / uTcScale);    // derivees hors de tout branchement (voisins ecartes ou non)
	float hd = scSetup(3.0);
	if (hd < -0.5)
		discard;
	if (hd < 0.5)
	{
		vec4 texColor = texture2D(uTex, vTc);
		if (texColor.a > fSolidThreshold)
		{
			gl_FragColor = mix(vColor, texColor, texColor.a);
			return;
		}
		int x,y;
		int kSize = 3;
		float minDist = float(kSize)+1.0;
		for (x = -kSize ; x <= kSize ; x++)
		{
			for (y = -kSize ; y <= kSize ; y++)
			{
				vec2 sampleCoord = vTc + vec2(float(x), float(y))*uTcScale;
				sampleCoord = sampleCoord/uTcScale;
				sampleCoord = sampleCoord + vec2(0.5, 0.5);
				sampleCoord.x = float(int(sampleCoord.x));
				sampleCoord.y = float(int(sampleCoord.y));
				sampleCoord = sampleCoord + vec2(0.5, 0.5);
				sampleCoord = sampleCoord * uTcScale;
				vec2 coordDiff = abs(vTc - sampleCoord)/uTcScale;
				vec4 texSample = texture2D(uTex, sampleCoord);
				if (texSample.a > fSolidThreshold)
				{
					float distance = sqrt((coordDiff.x*coordDiff.x) + (coordDiff.y*coordDiff.y));
					minDist = min(minDist, distance);
				}
			}
		}
		minDist = max(0.0, minDist-1.1);
		minDist = minDist/float(kSize);
		gl_FragColor = mix(vColor, vec4(0,0,0,0), minDist);
		return;
	}
	vec4 texColor = scHdColor();
	if (texColor.a > fSolidThreshold)
	{
		gl_FragColor = mix(vColorHD, texColor, texColor.a);
		return;
	}
	// contour : distance (unites du monde) au texel HD opaque le plus proche, sur 3 texels
	vec2 d = vTc / uTcScale - scPO;
	float minDist = 4.0;
	for (int x = -3; x <= 3; x++)
	{
		for (int y = -3; y <= 3; y++)
		{
			vec2 dd = floor(d) + vec2(float(x), float(y)) + 0.5;
			if (dd.x < 0.0 || dd.y < 0.0 || dd.x >= scPS.x || dd.y >= scPS.y)
				continue;
			vec4 s = scTex(scHdAt(floor(dd * scK)));
			if (s.a > fSolidThreshold)
			{
				vec2 df = abs(d - dd);
				minDist = min(minDist, sqrt(df.x * df.x + df.y * df.y));
			}
		}
	}
	minDist = max(0.0, minDist - 1.1) / 3.0;
	gl_FragColor = mix(vColorHD, vec4(0.0), minDist);
}
"""

for name, txt in [('FPDRAW', FPDRAW), ('FPTONE', FPTONE), ('FPSPRITE', FPSPRITE), ('FPSELECT', FPSELECT)]:
    open(os.path.join(OUT, name + '.GLSL'), 'w').write(txt)
open(os.path.join(OUT, 'VPDRAW.GLSL'), 'w').write(open(os.path.join(SH, 'VPDRAW.GLSL')).read())
print('ok', sorted(os.listdir(OUT)))
