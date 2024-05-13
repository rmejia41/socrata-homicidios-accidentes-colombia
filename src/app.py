import os
import pandas as pd
import geopandas as gpd
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, dash_table
import plotly.express as px
from sodapy import Socrata
from datetime import date
from dotenv import load_dotenv
import unidecode

# Load environment variables
load_dotenv()
MAPBOX_ACCESS_TOKEN = os.getenv('MAPBOX_ACCESS_TOKEN')
SOCRATA_APP_TOKEN = os.getenv('SOCRATA_APP_TOKEN')
if not MAPBOX_ACCESS_TOKEN:
    raise EnvironmentError("The Mapbox Access Token has not been set in the environment variables.")
px.set_mapbox_access_token(MAPBOX_ACCESS_TOKEN)
if not SOCRATA_APP_TOKEN:
    raise EnvironmentError("The Socrata App Token has not been set in the environment variables.")

# Function Definitions
def fetch_data(data_url, data_set, app_token):
    client = Socrata(data_url, app_token)
    client.timeout = 90
    results = client.get(data_set, limit=1500000)
    return pd.DataFrame.from_records(results)

def normalize_df(df):
    df['departamento'] = df['departamento'].apply(lambda x: unidecode.unidecode(x).upper().strip())
    df['municipio'] = df['municipio'].apply(lambda x: unidecode.unidecode(x).upper().replace('(CT)', '').strip())
    df['municipio'] = df['municipio'].replace('BOGOTA D.C.', 'BOGOTA D.C')
    df['armas_medios'] = df['armas_medios'].str.upper().str.strip()
    df['armas_medios'] = df['armas_medios'].replace(['NO REPOTADO', 'NO REPORTA'], 'NO REPORTADO')
    df['fecha_hecho'] = pd.to_datetime(df['fecha_hecho'], errors='coerce').dt.date
    df['genero'] = df['genero'].str.upper().str.strip()
    df['cantidad'] = df['cantidad'].astype(str).str.upper().str.strip()

    rename_columns = {
        'codigo_dane': 'CODIGO DANE',
        'armas_medios': 'ARMAS MEDIOS',
        'fecha_hecho': 'FECHA HECHO'
    }
    df.rename(columns=rename_columns, inplace=True)
    df.columns = [x.upper().replace('_', ' ') for x in df.columns]
    return df

def merge_and_clean_coordinates(df, latlong_df):
    merged_df = pd.merge(df, latlong_df, on=['DEPARTAMENTO', 'MUNICIPIO'], how='left', suffixes=(None, '_y'))
    if 'LATITUDE_y' in merged_df.columns and 'LONGITUDE_y' in merged_df.columns:
        merged_df['LATITUDE'] = merged_df['LATITUDE'].combine_first(merged_df['LATITUDE_y'])
        merged_df['LONGITUDE'] = merged_df['LONGITUDE'].combine_first(merged_df['LONGITUDE_y'])
        merged_df.drop(['LATITUDE_y', 'LONGITUDE_y'], axis=1, inplace=True)
    return merged_df

def remove_missing_coordinates(df):
    df = df.dropna(subset=['LATITUDE', 'LONGITUDE'])
    return df

def fill_missing_values(df):
    df['FECHA HECHO'] = df['FECHA HECHO'].fillna('No Reportado')
    return df

def extract_year_from_fecha_hecho(df):
    df['FECHA HECHO'] = pd.to_datetime(df['FECHA HECHO'], errors='coerce', format='%Y-%m-%d')
    df['YEAR'] = df['FECHA HECHO'].dt.year.astype('Int64').astype(str).replace('<NA>', 'No Reportado')
    return df

def drop_fecha_hecho(df):
    df.drop('FECHA HECHO', axis=1, inplace=True)
    return df

# Read Colombian Police Open Data
data_url = 'datos.gov.co'
data_set = 'ha6j-pa2r'

# Fetch data
df = fetch_data(data_url, data_set, SOCRATA_APP_TOKEN)
df = df[['departamento', 'municipio', 'codigo_dane', 'armas_medios', 'fecha_hecho', 'genero', 'cantidad']]

# Normalize columns
df = normalize_df(df)

# Read latitude and longitude data from the provided URL
url = "https://github.com/rmejia41/open_datasets/raw/main/Municipios.xlsx"
latlong_df = pd.read_excel(url)

# Merge data and consolidate coordinates
merged_df = merge_and_clean_coordinates(df, latlong_df)

# Remove records without latitude and longitude
merged_df = remove_missing_coordinates(merged_df)

# Fill other missing values
merged_df = fill_missing_values(merged_df)

# Extract year from 'FECHA HECHO'
merged_df = extract_year_from_fecha_hecho(merged_df)

# Drop 'FECHA HECHO'
merged_df = drop_fecha_hecho(merged_df)

# Prepare data for visualization
departments = sorted(merged_df['DEPARTAMENTO'].unique())
years = sorted(merged_df['YEAR'].unique())

# Add 'All Cases' options
departments.insert(0, 'All Cases')
years.insert(0, 'All Cases')

# Initialize the multipage Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SPACELAB], suppress_callback_exceptions=True)
server = app.server

# Load GeoJSON for municipalities
municipalities_geojson_path = 'https://github.com/rmejia41/open_datasets/raw/main/Servicios_Publicos_Municipios_d.json'
municipalities = gpd.read_file(municipalities_geojson_path)

# Load GeoJSON for departments
departments_geojson_path = 'https://github.com/rmejia41/open_datasets/raw/main/colombia-with-regions_1430.geojson'
departments_geojson = gpd.read_file(departments_geojson_path)

# Layout
app.layout = dbc.Container([
    dbc.Row([
        #dbc.Col(html.H2("Homicide-Traffic Cases in Colombia"), width=12),
        dbc.Col(
            dcc.Tabs(id='tabs', value='home', children=[
                dcc.Tab(label="Page 1", value='home'),
                dcc.Tab(label="Page 2", value='distribution')
            ]), width=12
        )
    ]),
    dbc.Row([
        dbc.Col(html.Div(id='page-content'), width=12)
    ])
], fluid=True)

# Page 1: "Home: Location of Homicide-Traffic Cases"
home_layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("Dashboard: Homicide Cases Associated with Traffic Accidents in Colombia",
                        className='text-center', style={'fontSize': '24px'}), width=12),  # Smaller font size for the title
        dbc.Col(html.H3(f"Data updated from 2010-01-01 to {date.today().strftime('%Y-%m-%d')}",
                        className='text-center', style={'fontSize': '18px'}), width=12)  # Smaller font size for the subtitle
    ]),
    dbc.Row([
        dbc.Col(html.A("Police Department Open Data",
                       href="https://www.datos.gov.co/Seguridad-y-Defensa/Homicidios-accidente-de-tr-nsito-Polic-a-Nacional/ha6j-pa2r/about_data",
                       target="_blank",
                       className="link",
                       style={'width': '100%', 'display': 'inline-block', 'text-align': 'right', 'fontSize': '80%'}),
                width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.Label("Select a Year:", className='mb-1'),
            dcc.Dropdown(
                id='home-year-dropdown',
                options=[{'label': year, 'value': year} for year in sorted(merged_df['YEAR'].unique())] + [{'label': 'All Cases', 'value': 'All Cases'}],
                value='All Cases',
                clearable=False
            )
        ], width=3),
        dbc.Col([
            html.Label("Select a Municipality:", className='mb-1'),
            dcc.Dropdown(
                id='home-municipio-dropdown',
                options=[{'label': mun, 'value': mun} for mun in sorted(merged_df['MUNICIPIO'].unique())] + [{'label': 'All Cases', 'value': 'All Cases'}],
                value='All Cases',
                clearable=False
            )
        ], width=3),
        dbc.Col([
            html.Label("Select Armas Medios:", className='mb-1'),
            dcc.Dropdown(
                id='home-armas-medios-dropdown',
                options=[{'label': armas, 'value': armas} for armas in sorted(merged_df['ARMAS MEDIOS'].unique())] + [{'label': 'All Cases', 'value': 'All Cases'}],
                value='All Cases',
                clearable=False
            )
        ], width=3)
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Row([html.Label("Select a visualization option:", className='mb-1')], className='mb-2'),
            dbc.Row([
                dbc.RadioItems(
                    id='map-radio',
                    options=[
                        {'label': 'Show Regional Borders', 'value': 'departments'},
                        {'label': 'Show Municipal Borders', 'value': 'municipalities'},
                        {'label': 'No Borders', 'value': 'none'}
                    ],
                    value='none',
                    inline=True
                )
            ])
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='map-graph', style={'height': '600px'}), width=12)
    ])
], fluid=True)


@app.callback(
    Output('map-graph', 'figure'),
    [
        Input('home-year-dropdown', 'value'),
        Input('home-municipio-dropdown', 'value'),
        Input('map-radio', 'value'),
        Input('home-armas-medios-dropdown', 'value')
    ]
)
def update_map(year, municipio, map_style, armas_medios):
    filtered_df = merged_df.copy()

    if year != 'All Cases':
        filtered_df = filtered_df[filtered_df['YEAR'] == year]

    if municipio != 'All Cases':
        filtered_df = filtered_df[filtered_df['MUNICIPIO'] == municipio]

    if armas_medios != 'All Cases':
        filtered_df = filtered_df[filtered_df['ARMAS MEDIOS'] == armas_medios]

    aggregated_data = filtered_df.groupby(['DEPARTAMENTO', 'MUNICIPIO', 'LATITUDE', 'LONGITUDE', 'GENERO', 'YEAR']).agg(
        Total_Cases=('CODIGO DANE', 'count')
    ).reset_index()

    total_cases_by_location = filtered_df.groupby(['DEPARTAMENTO', 'MUNICIPIO', 'YEAR']).agg(
        Total_Cases_By_Location=('CODIGO DANE', 'count')
    ).reset_index()

    aggregated_data = pd.merge(aggregated_data, total_cases_by_location, on=['DEPARTAMENTO', 'MUNICIPIO', 'YEAR'])
    aggregated_data['% Gender'] = (aggregated_data['Total_Cases'] / aggregated_data['Total_Cases_By_Location']) * 100

    fig = px.scatter_mapbox(
        aggregated_data,
        lat="LATITUDE",
        lon="LONGITUDE",
        hover_name="MUNICIPIO",
        hover_data={"DEPARTAMENTO": True, "Total_Cases": True, "% Gender": True, "GENERO": True, "YEAR": True},
        color="% Gender",
        size="Total_Cases",
        size_max=20,
        color_continuous_scale=px.colors.sequential.YlOrRd,
        zoom=5,
        mapbox_style="mapbox://styles/mapbox/navigation-day-v1"
    )

    # Adjust the size of the color bar
    fig.update_layout(
        coloraxis_colorbar=dict(len=0.5)
    )

    if map_style == 'departments':
        fig.add_trace(px.choropleth_mapbox(
            departments_geojson,
            geojson=departments_geojson.geometry,
            locations=departments_geojson.index,
            opacity=0.5,
            color_discrete_sequence=["#666666"],
            hover_name='name'
        ).data[0])
    elif map_style == 'municipalities':
        fig.add_trace(px.choropleth_mapbox(
            municipalities,
            geojson=municipalities.geometry,
            locations=municipalities.index,
            opacity=0.5,
            color_discrete_sequence=["#666666"],
            hover_name='MPIO_CNMBR'
        ).data[0])

    fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0}, hovermode='closest', uirevision='map-graph')
    return fig

# Page 2: "% Distribution of Homicide-Traffic Cases"
distribution_layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.Label('DEPARTMENT', style={'font-weight': 'bold'}),
            dcc.Dropdown(
                id='distribution-department-dropdown',
                options=[{'label': dept, 'value': dept} for dept in departments],
                value='All Cases',
                clearable=False,
                style={'width': '100%'}
            )
        ], width=3),
        dbc.Col([
            html.Label('YEAR', style={'font-weight': 'bold'}),
            dcc.Dropdown(
                id='distribution-year-dropdown',
                options=[{'label': yr, 'value': yr} for yr in years],
                value='All Cases',
                clearable=False,
                style={'width': '100%'}
            )
        ], width=3)
    ], className='mb-3'),
    dbc.Row([
        dbc.Col(dcc.Graph(id='cases-graph', style={'height': '50vh'}), width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.Label(
                "Use the Table Below to Filter the Data",
                style={'font-family': 'Helvetica, Arial, sans-serif', 'color': 'blue', 'font-size': '18px'}
            ),
            dash_table.DataTable(
                id='cases-table',
                columns=[
                    {'name': col, 'id': col} for col in merged_df.columns if col not in ['LATITUDE', 'LONGITUDE']
                ],
                filter_action='native',
                sort_action='native',
                page_action='native',
                page_size=5,
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'left', 'width': '100px'}
            )
        ], width=12)
    ])
], fluid=True)


@app.callback(
    [
        Output('cases-graph', 'figure'),
        Output('cases-table', 'data')
    ],
    [
        Input('distribution-department-dropdown', 'value'),
        Input('distribution-year-dropdown', 'value')
    ]
)
def update_graph_and_table(selected_department, selected_year):
    # Filter based on selected department and year
    filtered_df = merged_df.copy()
    if selected_department != 'All Cases':
        filtered_df = filtered_df[filtered_df['DEPARTAMENTO'] == selected_department]
    if selected_year != 'All Cases':
        filtered_df = filtered_df[filtered_df['YEAR'] == selected_year]

    # Replace 'NO REPOTADO' and 'NO REPORTA' with 'NO REPORTADO'
    filtered_df['GENERO'] = filtered_df['GENERO'].replace(['NO REPOTADO', 'NO REPORTA'], 'NO REPORTADO')

    # Convert 'CANTIDAD' column to numeric, handling errors
    filtered_df['CANTIDAD'] = pd.to_numeric(filtered_df['CANTIDAD'], errors='coerce').fillna(0)

    if selected_department == 'All Cases' and selected_year == 'All Cases':
        # Aggregating data by department
        department_data = filtered_df.groupby('DEPARTAMENTO', as_index=False)['CANTIDAD'].sum()

        # Create the bar chart
        fig = px.bar(
            department_data,
            x='DEPARTAMENTO',
            y='CANTIDAD',
            labels={'DEPARTAMENTO': 'Department', 'CANTIDAD': 'Number of Cases'},
            title='Homicide Cases by Department (All Cases)'
        )

        return fig, filtered_df.drop(['LATITUDE', 'LONGITUDE'], axis=1).to_dict('records')

    else:
        # Aggregating data by municipality and gender
        municipality_gender_data = filtered_df.groupby('GENERO', as_index=False)['CANTIDAD'].sum()

        # Check for zero total cases
        total_cases = municipality_gender_data['CANTIDAD'].sum()
        if total_cases == 0:
            return px.pie(), []

        # Calculate percentages
        municipality_gender_data['PERCENTAGE'] = municipality_gender_data['CANTIDAD'] / total_cases * 100

        # Create the pie chart
        title = 'Homicide Cases by Gender'
        if selected_department != 'All Cases':
            title += f' in {selected_department}'
        if selected_year != 'All Cases':
            title += f' ({selected_year})'

        fig = px.pie(
            municipality_gender_data,
            values='CANTIDAD',
            names='GENERO',
            title=title
        )
        fig.update_traces(textinfo='percent+label', pull=[0.1, 0])

        return fig, filtered_df.drop(['LATITUDE', 'LONGITUDE'], axis=1).to_dict('records')

@app.callback(
    Output('page-content', 'children'),
    [Input('tabs', 'value')]
)
def display_page(tab):
    if tab == 'home':
        return home_layout
    elif tab == 'distribution':
        return distribution_layout

if __name__ == '__main__':
    app.run_server(debug=False)